import asyncio
import httpx
import json
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError
from typing_extensions import Annotated

from config import BACKEND_BASE_URL, logger
from db import conversation, engine, message
from utility import store_operator_message
from utility.whatsapp import send_message, upload_media, send_media, typing_indicator

router = APIRouter(prefix="/api/v1", tags=["Operator Messages"])

# Legacy compatibility router without prefix for backward compatibility
legacy_router = APIRouter(tags=["Legacy Operator Messages"])
_logger = logger(__name__)

# Pydantic models for request validation
class OperatorMessageRequest(BaseModel):
    """Request model for operator messages"""
    receiverPhone: str = Field(..., description="Recipient phone number")
    message: str = Field(..., description="Message text")
    senderId: str = Field(..., description="Operator/sender ID")
    media: Optional[str] = Field(None, description="Media file ID")
    mimeType: Optional[str] = Field(None, description="Media MIME type")

class OperatorMessage(BaseModel):
    message: str = Field(..., description="The message text")
    phone: str = Field(..., description="Recipient's phone number")
    messageId: Optional[str] = Field(None, description="Optional message ID")
    media: Optional[Dict[str, str]] = Field(None, description="Optional media information")

def get_media_type_and_extension(mime_type: str) -> Tuple[str, str]:
    """
    Map MIME type to WhatsApp media type and file extension
    
    Args:
        mime_type: MIME type string
        
    Returns:
        Tuple of (media_type, file_extension)
    """
    mime_mapping = {
        "image/jpeg": ("image", ".jpg"),
        "image/jpg": ("image", ".jpg"),
        "image/png": ("image", ".png"),
        "image/webp": ("image", ".webp"),
        "video/mp4": ("video", ".mp4"),
        "video/3gpp": ("video", ".3gp"),
        "audio/aac": ("audio", ".aac"),
        "audio/mp4": ("audio", ".m4a"),
        "audio/mpeg": ("audio", ".mp3"),
        "audio/amr": ("audio", ".amr"),
        "audio/ogg": ("audio", ".ogg"),
        "application/pdf": ("document", ".pdf"),
        "application/vnd.ms-powerpoint": ("document", ".ppt"),
        "application/msword": ("document", ".doc"),
        "application/vnd.ms-excel": ("document", ".xls"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("document", ".docx"),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ("document", ".pptx"),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("document", ".xlsx"),
    }
    return mime_mapping.get(mime_type.lower(), ("document", ".bin"))

async def download_operator_media(file_id: str, mime_type: str) -> Optional[Dict]:
    """
    Download media file from backend server
    
    Args:
        file_id: File identifier
        mime_type: Media MIME type
        
    Returns:
        Dict with success status and file info or error
    """
    download_url = f"{BACKEND_BASE_URL}api/v1/get-sent-media"
    
    try:
        _logger.info(f"Downloading media: fileId={file_id}, mimeType={mime_type}")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                download_url,
                params={"fileId": file_id, "type": mime_type}
            )
        
        if response.status_code != 200:
            _logger.error(f"Failed to download media: {response.status_code} - {response.text}")
            return None
            
        # Get content type and content
        content_type = response.headers.get('content-type', '')
        content = response.content
        
        if not content:
            _logger.error("Empty content in media response")
            return None
            
        # Determine file extension from mime type
        media_type, file_ext = get_media_type_and_extension(mime_type)
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        # Upload to WhatsApp
        try:
            media_id = upload_media(temp_file_path, mime_type)
            if not media_id:
                _logger.error("Failed to upload media to WhatsApp")
                return None
                
            return {
                "id": media_id,
                "type": media_type,
                "mime_type": mime_type,
                "local_path": temp_file_path
            }
            
        except Exception as e:
            _logger.error(f"Error uploading media: {str(e)}", exc_info=True)
            return None
            
        finally:
            # Clean up temp file
            try:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            except Exception as e:
                _logger.warning(f"Error cleaning up temp file: {str(e)}")
                
    except Exception as e:
        _logger.error(f"Request error downloading media: {str(e)}")
        return None

async def store_operator_message_with_retry(message_text: str, phone: str, message_id: str = None, **kwargs):
    """
    Store operator message with automatic retry on connection errors
    
    IMPORTANT: This already uses async Celery task for graph sync via store_operator_message()
    """
    max_retries = 3
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            # Store message in database (includes async graph sync via Celery task)
            store_operator_message(
                message_text=message_text,
                user_ph=phone,
                external_msg_id=message_id,
                **kwargs
            )
            return True
            
        except (OperationalError, DBAPIError) as e:
            if attempt == max_retries - 1:
                _logger.error(f"Failed to store operator message after {max_retries} attempts: {str(e)}")
                raise
                
            _logger.warning(f"Database error (attempt {attempt + 1}/{max_retries}): {str(e)}")
            await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            
    return False

@router.get("/operatormsg")
async def operatormsg_health():
    """Health check for operator message endpoint"""
    return PlainTextResponse("THIS ENDPOINT IS UP AND RUNNING", status_code=200)

@router.post("/operator-message")
@router.post("/operator-message")
async def operatormsg(message_data: OperatorMessage):
    """
    Handle operator messages with full context sync
    
    CRITICAL FIX: Graph sync happens asynchronously via Celery task
    in store_operator_message() → sync_operator_message_to_graph_task
    """
    try:
        _logger.info(f"Received operator message: {message_data.model_dump_json(indent=2)}")
        
        # Extract required fields
        message_text = message_data.message.strip()
        phone = message_data.phone.strip()
        
        if not phone:
            _logger.error("Missing required field: phone")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number is required"
            )
        
        # Validate message content
        if not message_text and not message_data.media:
            _logger.error("Empty message with no media")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message text or media is required"
            )
            
        # Handle media if present
        media_data = None
        if message_data.media and 'id' in message_data.media and 'mimeType' in message_data.media:
            media_id = message_data.media['id']
            mime_type = message_data.media['mimeType']
            
            if media_id and mime_type:
                media_data = await download_operator_media(media_id, mime_type)
                if not media_data:
                    _logger.error(f"Failed to download media: {media_id}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to process media"
                    )
        
        # Send the message
        response = send_message(phone, message_text)
        message_id = response.get("messages", [{}])[0].get('id') if response else None
        
        # Store the message (includes async graph sync via Celery)
        try:
            await store_operator_message_with_retry(
                message_text=message_text,
                phone=phone,
                message_id=message_id,
                media=media_data
            )
            
            _logger.info(f"Successfully queued operator message for {phone}")
            return {
                "status": "success",
                "message": "Message queued for processing",
                "message_id": message_id
            }
            
        except Exception as e:
            _logger.error(f"Error storing operator message: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process message"
            )
            
    except HTTPException as he:
        raise he
    except Exception as e:
        _logger.error(f"Unexpected error in operatormsg: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


# Legacy compatibility endpoints (without /api/v1/ prefix)
# These maintain backward compatibility with existing web interface

@legacy_router.get("/operatormsg")
async def legacy_operatormsg_health():
    """Health check for legacy operator message endpoint"""
    return PlainTextResponse("THIS ENDPOINT IS UP AND RUNNING", status_code=200)


@legacy_router.post("/operator-message")
async def legacy_operatormsg(message_data: OperatorMessage):
    """Legacy operator message endpoint for backward compatibility"""
    return await operatormsg(message_data)