from flask import Blueprint, request, jsonify
from config import logger, BACKEND_BASE_URL
from utility import store_operator_message
from utility.whatsapp import send_message, upload_media, send_media
from typing import Tuple, Optional, Dict
import tempfile
import requests
import os
import json

operator_bp = Blueprint('operatormsg', __name__)
_logger = logger(__name__)

def get_media_type_and_extension(mime_type: str) -> Tuple[str, str]:

    mime_mapping = {
        # Images
        "image/jpeg": ("image", ".jpg"),
        "image/jpg": ("image", ".jpg"),
        "image/png": ("image", ".png"),
        "image/webp": ("image", ".webp"),
        
        # Videos
        "video/mp4": ("video", ".mp4"),
        "video/3gpp": ("video", ".3gp"),
        
        # Audio
        "audio/aac": ("audio", ".aac"),
        "audio/mp4": ("audio", ".m4a"),
        "audio/mpeg": ("audio", ".mp3"),
        "audio/amr": ("audio", ".amr"),
        "audio/ogg": ("audio", ".ogg"),
        
        # Documents
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
        
        # Download the media file
        response = requests.get(
            download_url,
            params={
                "fileId": file_id,
                "type": mime_type
            },
            stream=True,
            timeout=30
        )
        
        if not response.ok:
            _logger.error(f"Failed to download media. Status: {response.status_code}")
            return {
                "success": False,
                "error": f"Download failed with status {response.status_code}"
            }
        
        # Determine file extension and media type
        media_type, file_ext = get_media_type_and_extension(mime_type)
        
        # Save to temporary file
        temp_file = tempfile.NamedTemporaryFile(
            delete=False, 
            suffix=file_ext,
            prefix=f"operator_media_{file_id}_"
        )
        
        # Write content in chunks
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
    
   
@operator_bp.route("/operatormsg", methods=["GET","POST"])
def operatormsg():
    """Handle operator messages with full context sync"""
    if request.method == "POST":
        data = request.get_json(force=True)
        
        _logger.info(f"DATA RECEIVED: {json.dumps(data, indent=2)}")
        # print(f"DATA RECEIVED: {data}, {type(data)}")
        # if data:
        #     return "OK", 200
        # else:
        #     return "FAILED", 500


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
                    response = send_media(media_type, phone, media_id)
                    message_id = response.get("messages", [{}])[0].get('id') if response else None

                    # Store and sync to graph
                    store_operator_message(message, phone, message_id, media_id=media_id, mime_type=mime_type, sender_id = sender_id)
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

                # Store and sync to graph
                store_operator_message(message, phone, message_id)

                return jsonify({"status": "success", "message_id": message_id})

            except Exception as e:
                _logger.error(f"Failed to send operator message: {e}")
                return jsonify({"status": "error", "error": str(e)}), 500
        
