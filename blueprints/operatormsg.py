from flask import Blueprint, request, jsonify
from config import logger, BACKEND_BASE_URL
from utility import store_operator_message
from utility.whatsapp import send_message, upload_media, send_media, typing_indicator
from typing import Tuple, Optional, Dict
from db import engine, conversation, message
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, DBAPIError
import tempfile
import requests
import os
import json
import time

operator_bp = Blueprint('operatormsg', __name__)
_logger = logger(__name__)

def get_media_type_and_extension(mime_type: str) -> Tuple[str, str]:
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


def download_operator_media(file_id: str, mime_type: str) -> Optional[Dict]:
    download_url = f"{BACKEND_BASE_URL}api/v1/get-sent-media"
    
    try:
        _logger.info(f"Downloading media: fileId={file_id}, mimeType={mime_type}")
        
        response = requests.get(
            download_url,
            params={"fileId": file_id, "type": mime_type},
            stream=True,
            timeout=30
        )
        
        if not response.ok:
            _logger.error(f"Failed to download media. Status: {response.status_code}")
            return {"success": False, "error": f"Download failed with status {response.status_code}"}
        
        media_type, file_ext = get_media_type_and_extension(mime_type)
        
        temp_file = tempfile.NamedTemporaryFile(
            delete=False, 
            suffix=file_ext,
            prefix=f"operator_media_{file_id}_"
        )
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                temp_file.write(chunk)
        
        temp_file.close()
        file_path = temp_file.name
        file_size = os.path.getsize(file_path)
        
        _logger.info(f"Media downloaded successfully: {file_path} ({file_size} bytes)")
               
        return {
            "success": True,
            "file_path": file_path,
            "media_type": media_type,
            "file_size": file_size
        }
        
    except requests.Timeout:
        _logger.error(f"Download timeout for file {file_id}")
        return {"success": False, "error": "Download timeout"}
        
    except requests.RequestException as e:
        _logger.exception(f"Failed to download media {file_id}: {str(e)}")
        return {"success": False, "error": str(e)}
        
    except Exception as e:
        _logger.exception(f"Unexpected error downloading media {file_id}: {str(e)}")
        return {"success": False, "error": str(e)}


def store_operator_message_with_retry(message_text: str, phone: str, message_id: str = None, **kwargs):
    """
    Store operator message with automatic retry on connection errors
    
    This wraps the store function to handle transient DB issues
    """
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            store_operator_message(message_text, phone, message_id, **kwargs)
            return  # Success!
            
        except (OperationalError, DBAPIError) as e:
            error_msg = str(e).lower()
            is_connection_error = any(
                keyword in error_msg 
                for keyword in ['ssl', 'connection', 'closed', 'broken', 'timeout', 'network']
            )
            
            if is_connection_error and attempt < max_retries - 1:
                backoff = 0.1 * (2 ** attempt)
                _logger.warning(f"DB store failed (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}")
                _logger.info(f"Retrying in {backoff:.2f}s...")
                time.sleep(backoff)
                continue
            
            # Not a connection error or out of retries
            _logger.error(f"Failed to store operator message after {attempt + 1} attempts")
            raise
   
@operator_bp.route("/operatormsg", methods=["GET","POST"])
def operatormsg():
    """Handle operator messages with full context sync"""
    if request.method == "POST":
        data = request.get_json(force=True)
        
        _logger.info(f"DATA RECEIVED: {json.dumps(data, indent=2)}")
        
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
    
        required = ["receiverPhone", "message", "senderId"]
        missing = [f for f in required if f not in data]
        
        if missing:
            return jsonify({"status": "error", "message": f"Missing: {', '.join(missing)}"}), 400
        
        phone = data["receiverPhone"]
        message = data["message"]
        sender_id = data["senderId"]
        media = data.get("media", None)
        mime_type = data.get("mimeType", None)

        if media and mime_type:
            # Handle media message
            downloaded_content = download_operator_media(media, mime_type)

            if downloaded_content["success"]:
                file_path = downloaded_content["file_path"]
                media_type = downloaded_content["media_type"]

                try:
                    # Upload media to WhatsApp
                    media_id = upload_media(file_path)
                    if not media_id:
                        raise Exception("Media upload failed, no media ID returned")
                    
                    # Send media message
                    response = send_media(media_type, phone, media_id, message)
                    message_id = response.get("messages", [{}])[0].get('id') if response else None

                    # Store with retry logic
                    store_operator_message_with_retry(
                        message, phone, message_id, 
                        media_id=media_id, 
                        mime_type=mime_type, 
                        sender_id=sender_id
                    )
                    
                    return jsonify({"status": "success", "message_id": message_id})

                except Exception as e:
                    _logger.error(f"Failed to send operator media message: {e}")
                    return jsonify({"status": "error", "error": str(e)}), 500

                finally:
                    # Clean up temporary file
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        _logger.info(f"Temporary file {file_path} deleted")
                        
        else:
            # Handle text message    
            try:
                # Send to WhatsApp
                response = send_message(phone, message)
                message_id = response.get("messages", [{}])[0].get('id') if response else None

                # Store with retry logic - THIS IS THE KEY CHANGE
                store_operator_message_with_retry(message, phone, message_id, sender_id=sender_id)

                return jsonify({"status": "success", "message_id": message_id}), 200

            except Exception as e:
                _logger.error(f"Failed to send operator message: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500