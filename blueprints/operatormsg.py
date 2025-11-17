from flask import Blueprint, request, jsonify
from config import logger, BACKEND_BASE_URL
from utility import store_operator_message
from utility.whatsapp import send_message, typing_indicator
from typing import Tuple
from db import engine, conversation, message
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, DBAPIError
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


def download_operator_media(file_id: str, mime_type: str):
    """
    Download media from interface backend
    
    IMPORTANT: This function can take 30+ seconds for large files.
    It should ONLY be called from Celery workers with proper timeouts.
    """
    import requests
    import tempfile
    import os
    
    download_url = f"{BACKEND_BASE_URL}api/v1/get-sent-media"
    
    try:
        _logger.info(f"Downloading media: fileId={file_id}, mimeType={mime_type}")
        
        # Add streaming timeout (separate from Gunicorn timeout)
        response = requests.get(
            download_url,
            params={"fileId": file_id, "type": mime_type},
            stream=True,
            timeout=(10, 120)  # (connect_timeout, read_timeout) = 10s connect, 120s read
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
        
        # Download with progress logging
        bytes_downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                temp_file.write(chunk)
                bytes_downloaded += len(chunk)
                
                # Log progress every 1MB
                if bytes_downloaded % (1024 * 1024) == 0:
                    _logger.info(f"Downloaded {bytes_downloaded / (1024*1024):.1f}MB...")
        
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
    """Store operator message with automatic retry on connection errors"""
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            store_operator_message(message_text, phone, message_id, **kwargs)
            return
            
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
            
            _logger.error(f"Failed to store operator message after {attempt + 1} attempts")
            raise
   

@operator_bp.route("/operatormsg", methods=["GET","POST"])
def operatormsg():
    """
    Handle operator messages
    
    CRITICAL FIX: Media processing now happens asynchronously via Celery
    to prevent Gunicorn worker timeouts on slow downloads.
    """
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
            # CRITICAL FIX: Offload media processing to Celery
            # This prevents blocking the Gunicorn worker on slow downloads
            from tasks import process_operator_media_task
            
            try:
                # Queue the media processing task
                task = process_operator_media_task.apply_async(
                    args=[phone, media, mime_type, message, sender_id],
                    queue='media',
                    priority=6  # High priority for operator actions
                )
                
                _logger.info(f"Queued media processing task {task.id[:8]} for {phone}")
                
                # Return immediately (don't wait for Celery task)
                return jsonify({
                    "status": "accepted",
                    "message": "Media message queued for processing",
                    "task_id": task.id
                }), 202  # 202 Accepted
                
            except Exception as e:
                _logger.error(f"Failed to queue media processing: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
                        
        else:
            # Handle text message (keep synchronous - it's fast)
            try:
                from utility.whatsapp import send_message
                
                # Send to WhatsApp
                response = send_message(phone, message)
                message_id = response.get("messages", [{}])[0].get('id') if response else None

                # Store in DB (async graph sync via Celery)
                store_operator_message_with_retry(message, phone, message_id, sender_id=sender_id)
                
                _logger.info(f"Operator text message sent to {phone}")

                return jsonify({"status": "success", "message_id": message_id}), 200

            except Exception as e:
                _logger.error(f"Failed to send operator message: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
    
    elif request.method == "GET":
        return "THIS ENDPOINT IS UP AND RUNNING", 200