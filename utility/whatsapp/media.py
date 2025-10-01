"""
WhatsApp media handling functions (upload, send, download)
"""
import os
import json
import requests
import mimetypes
from typing import Optional, Dict
from config import logger
from .constants import API_BASE, BASE_URL, get_headers, get_auth_header
from .errors import handle_error

_logger = logger(__name__)

def get_mime_type(file_path: str) -> str:
    """
    Detect MIME type from file path
    
    Args:
        file_path: Path to the file
        
    Returns:
        MIME type string
    """
    # Try to guess from extension
    mime_type, _ = mimetypes.guess_type(file_path)
    
    if mime_type:
        return mime_type
    
    # Fallback: detect from extension manually
    ext = os.path.splitext(file_path)[1].lower()
    
    mime_map = {
        # Images
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
        
        # Videos
        '.mp4': 'video/mp4',
        '.3gp': 'video/3gpp',
        
        # Audio
        '.aac': 'audio/aac',
        '.m4a': 'audio/mp4',
        '.mp3': 'audio/mpeg',
        '.amr': 'audio/amr',
        '.ogg': 'audio/ogg',
        
        # Documents
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xls': 'application/vnd.ms-excel',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    }
    
    return mime_map.get(ext, 'application/octet-stream')


def upload_media(file_path: str) -> Optional[str]:
    """
    Upload any media file to WhatsApp
    
    Supports: images, videos, audio, documents
    Automatically detects MIME type from file extension
    
    Args:
        file_path: Path to the media file
        
    Returns:
        Media ID if successful, None otherwise
        
    Example:
        >>> media_id = upload_media("/path/to/image.jpg")
        >>> media_id = upload_media("/path/to/video.mp4")
        >>> media_id = upload_media("/path/to/audio.mp3")
    """
    # Validate file exists
    if not os.path.exists(file_path):
        _logger.error("File not found: %s", file_path)
        return None
    
    # Detect MIME type
    mime_type = get_mime_type(file_path)
    file_name = os.path.basename(file_path)
    
    _logger.info(f"Uploading file: {file_name} (MIME: {mime_type})")
    
    url = f"{API_BASE}/media"
    headers = get_auth_header()
    
    # Open file for upload
    file_handle = None
    try:
        file_handle = open(file_path, "rb")
        
        files = {
            "file": (file_name, file_handle, mime_type)
        }
        
        data = {
            "messaging_product": "whatsapp"
        }
        
        # Upload
        response = requests.post(url, headers=headers, files=files, data=data)
        _logger.info("Media upload response: %s", response.status_code)
        
        if response.ok:
            response_data = response.json()
            media_id = response_data.get("id")
            _logger.info("Media uploaded successfully: %s (ID: %s)", file_name, media_id)
            _logger.debug("Response JSON: %s", response_data)
            return media_id
        
        # Handle error
        _logger.error("Media upload failed. Status: %s", response.status_code)
        try:
            error_obj = response.json()
            _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
            handle_error(error_obj)
        except ValueError:
            _logger.error("Response not valid JSON: %s", response.text)
        
        return None
        
    except requests.RequestException as e:
        _logger.exception("Media upload request failed: %s", str(e))
        return None
        
    except Exception as e:
        _logger.exception("Unexpected error during upload: %s", str(e))
        return None
        
    finally:
        # Always close file handle
        if file_handle:
            file_handle.close()
            _logger.debug("File handle closed for: %s", file_path)


def upload_video(file_path: str) -> Optional[str]:
    """
    Upload a video file to WhatsApp (deprecated, use upload_media instead)
    
    Args:
        file_path: Path to the video file
        
    Returns:
        Media ID if successful, None otherwise
    """
    _logger.warning("upload_video() is deprecated, use upload_media() instead")
    return upload_media(file_path)


def send_media(media_type: str, user_ph: str, media_id: str, caption: str = "") -> dict:
    """
    Send media (audio, image, video) to a user
    
    Args:
        media_type: Type of media ('audio', 'image', 'video')
        user_ph: Recipient phone number
        media_id: ID of the uploaded media
        caption: Optional caption for image/video
        
    Returns:
        Response data
    """
    url = f"{API_BASE}/messages"

    media_dict = None

    if media_type == "audio":
        media_dict = {"id": media_id}
    elif media_type in ["image", "video"]:
        media_dict = {"id": media_id, "caption": caption}
            
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": user_ph,
        "type": media_type,
        f"{media_type}": media_dict
    }

    try:
        # _logger.info(f"DATA BEFORE SENDING! URL:{url}, HEADERS: {get_headers()}, DATA:{data}")
        response = requests.post(url, headers=get_headers(), json=data)
        _logger.info("Media send response for %s: %s", media_id, response.status_code)
        
        if response.ok:
            _logger.info("Media %s sent successfully to %s", media_id, user_ph)
            # _logger.debug("Response JSON: %s", response.json())
            return response.json()
        else:
            _logger.error("Failed to send media %s. Status: %s", media_id, response.status_code)
            try:
                error_obj = response.json()
                _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
                handle_error(error_obj)
                return response.json()
            except ValueError:
                _logger.error("Response not valid JSON: %s", response.text)
                return response.json()
                
    except requests.RequestException as e:
        _logger.exception("Failed to send media %s: %s", media_id, str(e))
        return response.json()


def download_media(media_id: str) -> Optional[Dict]:
    """
    Download media file from WhatsApp
    
    Args:
        media_id: ID of the media to download
        
    Returns:
        Dict with 'content_type', 'data', and 'mime_type' if successful, None otherwise
    """
    url = f"{BASE_URL}/{media_id}/"
    headers = get_auth_header()

    try:
        _logger.info(f"GET {url}")
        response = requests.get(url, headers=headers)
        _logger.info("Media URL fetch response for %s: %s", media_id, response.status_code)

        if response.ok:
            response_data = response.json()
            _logger.info("Media URL received for %s", media_id)
            _logger.debug("Response JSON: %s", response_data)

            dl_url = response_data.get("url")
            if not dl_url:
                _logger.error("No download URL in response for %s", media_id)
                return None

            _logger.info("Starting media download from %s", dl_url)
            dl_resp = requests.get(dl_url, headers=headers, stream=True)

            if dl_resp.ok:
                _logger.info("Media downloaded for %s", media_id)
                return {
                    "content_type": dl_resp.headers.get("Content-Type"),
                    "data": dl_resp.content,
                    "mime_type": response_data["mime_type"]
                }
            else:
                _logger.error("Failed to download media for %s. Status: %s", media_id, dl_resp.status_code)
                try:
                    error_obj = dl_resp.json()
                    _logger.error("Download error response: %s", json.dumps(error_obj, indent=2))
                    handle_error(error_obj)
                except ValueError:
                    _logger.error("Download response not valid JSON: %s", dl_resp.text)
                return None

        # Outer API fetch failed
        _logger.error("Failed to fetch media URL for %s. Status: %s", media_id, response.status_code)
        try:
            error_obj = response.json()
            _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
            handle_error(error_obj)
        except ValueError:
            _logger.error("Response not valid JSON: %s", response.text)
        return None

    except requests.RequestException as e:
        _logger.exception("Media URL fetch request failed for %s: %s", media_id, str(e))
        return None


def get_url(media_id: str) -> Optional[Dict]:
    """
    Get the download URL for a media file
    
    Args:
        media_id: ID of the media
        
    Returns:
        Dict with 'url' key if successful, dict with 'error' key if failed
    """
    url = f"{BASE_URL}/{media_id}/"
    headers = get_auth_header()

    try:
        _logger.info(f"GET {url}")
        response = requests.get(url, headers=headers)
        _logger.info("Media URL fetch response for %s: %s", media_id, response.status_code)

        if response.ok:
            response_data = response.json()
            _logger.info("Media URL received for %s", media_id)
            _logger.debug("Response JSON: %s", response_data)

            dl_url = response_data.get("url")
                
            if not dl_url:
                _logger.error("No download URL in response for %s", media_id)
                return {"error": f"No download URL in response for {media_id}"}
            else:
                return {"url": dl_url}
            
        _logger.error("Failed to fetch media URL for %s. Status: %s", media_id, response.status_code)
        try:
            error_obj = response.json()
            _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
            handle_error(error_obj)
        except ValueError:
            _logger.error("Response not valid JSON: %s", response.text)
        return None

    except requests.RequestException as e:
        message = f"Media URL fetch request failed for {media_id}, {str(e)}"
        _logger.exception(message)
        return {"error": message}