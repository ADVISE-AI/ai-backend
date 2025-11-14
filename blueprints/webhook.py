from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Any
from config import logger, VERIFY_TOKEN
from utility import normalize_webhook_payload, is_duplicate, get_message_buffer
from tasks import update_message_status_task, check_buffer_task
import json
import time

router = APIRouter()
_logger = logger(__name__)

message_buffer = get_message_buffer()

# Pydantic models for type safety
class WebhookVerification(BaseModel):
    """Model for webhook verification query parameters"""
    hub_mode: str = Field(alias="hub.mode")
    hub_challenge: str = Field(alias="hub.challenge")
    hub_verify_token: str = Field(alias="hub.verify_token")
    
    class Config:
        populate_by_name = True


@router.api_route("/webhook", methods=["GET", "POST"])
async def webhook(request: Request):
    """
    Main webhook endpoint for WhatsApp Business API
    Handles both verification (GET) and incoming messages/statuses (POST)
    """
    
    if request.method == "GET":
        # Handle GET request (webhook verification)
        query_params = dict(request.query_params)
        mode = query_params.get('hub.mode')
        token = query_params.get('hub.verify_token')
        challenge = query_params.get('hub.challenge')
        
        if mode and token:
            if mode == 'subscribe' and token == VERIFY_TOKEN:
                _logger.info("Webhook verified successfully")
                return PlainTextResponse(content=challenge, status_code=200)
            else:
                _logger.warning("Webhook verification failed")
                return JSONResponse(
                    content="Verification token mismatch", 
                    status_code=403
                )
                
        return JSONResponse(
            content="Invalid request", 
            status_code=400
        )
    
    elif request.method == "POST":
        """
        WhatsApp webhook handler (POST)
        
        Receives incoming messages and status updates from WhatsApp.
        Handles message deduplication, buffering, and async processing.
        """
        try:
            # Step 1: Parse and validate incoming JSON
            data = await request.json()
            
            if not data:
                _logger.warning("Received empty webhook payload")
                return JSONResponse(content={"status": "ok"}, status_code=200)
        
            _logger.info(f"RECEIVED WHATSAPP WEBHOOK DATA: {json.dumps(data, indent=2)}")
            
            # Step 2: Normalize the webhook payload
            try:
                normalized_data = normalize_webhook_payload(data)
            except KeyError as e:
                _logger.error(f"Missing required field during normalization: {e}, Raw data: {json.dumps(data)}")
                return JSONResponse(content={"status": "ok"}, status_code=200)
            except Exception as e:
                _logger.error(f"Failed to normalize payload: {e}, Raw data: {json.dumps(data)}")
                return JSONResponse(content={"status": "ok"}, status_code=200)
            
            # Step 3: Check if normalization resulted in error
            if normalized_data.get("type") == "error" or normalized_data.get("error"):
                _logger.error(f"Normalization error: {normalized_data}")
                return JSONResponse(content={"status": "ok"}, status_code=200)
            
            # Step 4: Validate normalized data has required fields
            if not normalized_data.get("type"):
                _logger.error(f"Missing 'type' in normalized data: {normalized_data}")
                return JSONResponse(content={"status": "ok"}, status_code=200)
            
            # Step 5: Handle inbound messages
            if normalized_data["type"] == "inbound":
                try:
                    # Validate required fields for inbound messages
                    if not normalized_data.get("from") or not normalized_data["from"].get("phone"):
                        _logger.error(f"Missing 'from.phone' in inbound message: {normalized_data}")
                        return JSONResponse(content={"status": "ok"}, status_code=200)
                    
                    if not normalized_data["from"].get("message_id"):
                        _logger.error(f"Missing 'from.message_id' in inbound message: {normalized_data}")
                        return JSONResponse(content={"status": "ok"}, status_code=200)
                    
                    phone = normalized_data["from"]["phone"]
                    message_id = normalized_data["from"]["message_id"]
                    
                    # Check for duplicate messages
                    if is_duplicate(message_id, phone):
                        _logger.info(f"Duplicate message {message_id} from {phone} ignored")
                        return JSONResponse(content={"status": "ok"}, status_code=200)
                    
                    # Add message to buffer and check if it's the first message in this burst
                    is_first_message = message_buffer.add_message(phone, normalized_data)
                    
                    if is_first_message:
                        # Schedule buffer check after debounce time (2 seconds for better UX)
                        _logger.info(f"Scheduling buffer check for {phone} in 2 seconds")
                        check_buffer_task.apply_async(
                            args=[phone],  # phone only
                            countdown=2,
                            queue='messages',
                            priority=5
                        )
                    else:
                        _logger.info(f"Message from {phone} added to existing buffer (not first message)")
                    
                    return JSONResponse(content={"status": "ok"}, status_code=200)
                
                except Exception as e:
                    _logger.error(f"Error processing inbound message: {e}", exc_info=True)
                    return JSONResponse(content={"status": "ok"}, status_code=200)
            
            # Step 6: Handle status updates (delivery, read, sent, failed)
            elif normalized_data["type"] == "status":
                try:
                    status_msg_id = normalized_data.get('id', 'unknown')
                    status = normalized_data.get('status', 'unknown')
                    
                    _logger.info(f"Message status update received: ID={status_msg_id}, Status={status}")
                    
                    # Queue the status update task asynchronously
                    update_message_status_task.apply_async(
                        args=[normalized_data],
                        queue='status',
                        priority=2
                    )
                    
                    _logger.info(f"Status update task queued for message {status_msg_id}")
                    
                    return JSONResponse(content={"status": "ok"}, status_code=200)
                
                except Exception as e:
                    _logger.error(f"Error processing status update: {e}", exc_info=True)
                    return JSONResponse(content={"status": "ok"}, status_code=200)
            
            # Step 7: Handle unknown message types
            else:
                msg_type = normalized_data.get("type", "unknown")
                _logger.warning(f"Unknown message type received: {msg_type}, Data: {json.dumps(normalized_data, indent=2)}")
                return JSONResponse(content={"status": "ok"}, status_code=200)
        
        except json.JSONDecodeError as e:
            _logger.error(f"Invalid JSON in webhook payload: {e}")
            return JSONResponse(content={"status": "ok"}, status_code=200)
        
        except Exception as e:
            _logger.error(f"Unexpected error in webhook POST handler: {e}", exc_info=True)
            return JSONResponse(content={"status": "ok"}, status_code=200)


# Optional: Health check endpoint for the webhook
@router.get("/webhook/health")
async def webhook_health():
    """
    Health check endpoint to verify webhook service is running
    """
    try:
        return {
            "status": "ok",
            "service": "webhook",
            "timestamp": time.time()
        }
    except Exception as e:
        _logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "error": str(e)}
        )