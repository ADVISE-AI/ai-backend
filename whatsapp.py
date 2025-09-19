import os
import json
import requests
from typing import Dict, Optional, List, Union
from config import WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, logger

_logger = logger(__name__)


BASE_URL= "https://graph.facebook.com/v23.0/"
API_BASE = BASE_URL + WHATSAPP_PHONE_NUMBER_ID

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _handle_error(error_obj: Dict) -> None:
    error = error_obj.get("error", {})
    error_code = error.get("code")
    error_message = error.get("message", "Unknown error")

    error_mappings = {
        0: "AuthException. Get a new access token.",
        3: "Failed API method. Check app permissions.",
        10: "Permission denied.",
        190: "Access token expired.",
        368: "Temporarily blocked due to policy violations.",
    }

    message = error_mappings.get(error_code, f"Unknown error code: {error_code}")
    _logger.error(f"Error {error_code}: {message} - {error_message}")


def send_message(to: str, message: str):
    url = f"{API_BASE}/messages"
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    try:
        response = requests.post(url, headers=_headers(), json=data)
        _logger.info("Message send response: %s", response.status_code)
        resp_data = None
        try:
            resp_data = response.json()
        except Exception as e:
            _logger.error(f"Exception: {e}")
            _logger.error("Response not valid JSON: %s", response.text)

        if response.ok:
            _logger.info("Message sent successfully to %s", to)
            _logger.debug("Response JSON: %s", response.json())
            return resp_data
        else:
            _logger.error("Failed to send message. Status: %s", response.status_code)
            _logger.error("Error response: %s", json.dumps(resp_data, indent=2))
            return resp_data

    except requests.RequestException as e:
        _logger.exception("HTTP request failed: %s", str(e))


def typing_indicator(msg_id: str) -> bool:
    url = f"{API_BASE}/messages"
    data = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": msg_id,
        "typing_indicator":{
            "type": "text"
        }
    }

    try:
        response = requests.post(url, headers=_headers(), json=data)
        _logger.info("Typing indicator response: %s", response.status_code)

        if response.ok:
            _logger.info("Typing indicator sent for message %s", msg_id)
            _logger.debug("Response JSON: %s", response.json())
            return True

        _logger.error("Failed to send typing indicator. Status: %s", response.status_code)
        try:
            error_obj = response.json()
            _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
            _handle_error(error_obj)
        except ValueError:
            _logger.error("Response not valid JSON: %s", response.text)
        return False

    except requests.RequestException as e:
        _logger.exception("Failed to send typing indicator: %s", str(e))
        return False


def upload_video(file_path: str) -> Optional[str]:
    if not os.path.exists(file_path):
        _logger.error("File not found: %s", file_path)
        return None

    url = f"{API_BASE}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    files = {"file": (os.path.basename(file_path), open(file_path, "rb"), "video/mp4")}
    data = {"messaging_product": "whatsapp"}

    try:
        response = requests.post(url, headers=headers, files=files, data=data)
        _logger.info("Video upload response: %s", response.status_code)

        if response.ok:
            response_data = response.json()
            media_id = response_data.get("id")
            _logger.info("Video uploaded successfully: %s", media_id)
            _logger.debug("Response JSON: %s", response_data)
            return media_id

        _logger.error("Video upload failed. Status: %s", response.status_code)
        try:
            error_obj = response.json()
            _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
            _handle_error(error_obj)
        except ValueError:
            _logger.error("Response not valid JSON: %s", response.text)
        return None

    except requests.RequestException as e:
        _logger.exception("Video upload request failed: %s", str(e))
        return None
    finally:
        if "file" in files:
            files["file"][1].close()


def send_media(media_type: str, user_ph: str, media_id: str, caption: str = "") -> dict:
    url = f"{API_BASE}/messages"


    media_dict = None

    if media_type == "audio":
        media_dict = {
            "id": media_id
        }

    elif media_type in ["image", "video"]:
        media_dict = {
            "id": media_id, 
            "caption": caption
        }
            
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": user_ph,
        "type": media_type,
        f"{media_type}": media_dict
    }

    try:
        _logger.info(f"DATA BEFORE SENDING! URL:{url}, HEADERS: {_headers()}, DATA:{data}")
        response = requests.post(url, headers=_headers(), json=data)
        _logger.info("Video send response for media %s: %s", media_id, response.status_code)
        _logger.info(f"RESPONSE: {response.json()}")
        if response.ok:
            _logger.info("Video %s sent successfully to %s", media_id, user_ph)
            _logger.debug("Response JSON: %s", response.json())
            return response.json()
        else:
            _logger.error("Failed to send video %s. Status: %s", media_id, response.status_code)
            try:
                error_obj = response.json()
                _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
                _handle_error(error_obj)
                return response.json()
            except ValueError:
                _logger.error("Response not valid JSON: %s", response.text)
                return response.json()
    except requests.RequestException as e:
        _logger.exception("Failed to send video %s: %s", media_id, str(e))
        return response.json()



def download_media(media_id: str) -> Optional[Dict]:
    url = f"{BASE_URL}/{media_id}/"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}

    try:
        _logger.info(f" GET {url}")
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
                    _handle_error(error_obj)
                except ValueError:
                    _logger.error("Download response not valid JSON: %s", dl_resp.text)
                return None

        # Outer API fetch failed
        _logger.error("Failed to fetch media URL for %s. Status: %s", media_id, response.status_code)
        try:
            error_obj = response.json()
            _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
            _handle_error(error_obj)
        except ValueError:
            _logger.error("Response not valid JSON: %s", response.text)
        return None

    except requests.RequestException as e:
        _logger.exception("Media URL fetch request failed for %s: %s", media_id, str(e))
        return None


    
def get_url(media_id):
    url = f"{BASE_URL}/{media_id}/"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}

    try:
        _logger.info(f" GET {url}")
        response = requests.get(url, headers=headers)
        _logger.info("Media URL fetch response for %s: %s", media_id, response.status_code)

        if response.ok:
            response_data = response.json()
            _logger.info("Media URL received for %s", media_id)
            _logger.debug("Response JSON: %s", response_data)

            dl_url = response_data.get("url")
                
            if not dl_url:
                _logger.error("No download URL in response for %s", media_id)
                return {
                    "error": f"No download URL in response for {media_id}"
                }
            else:
                return {
                    "url": dl_url
                }
            
        _logger.error("Failed to fetch media URL for %s. Status: %s", media_id, response.status_code)
        try:
            error_obj = response.json()
            _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
            _handle_error(error_obj)
        except ValueError:
            _logger.error("Response not valid JSON: %s", response.text)
        return None

    except requests.RequestException as e:
        message = f"Media URL fetch request failed for {media_id}, {str(e)}"
        _logger.exception(message)
        return {
            "error": message
        }
