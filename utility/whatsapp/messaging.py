"""
WhatsApp messaging functions (text messages, typing indicators)
"""

import json
import requests
from typing import Optional
from config import logger
from .constants import API_BASE, get_headers
from .errors import handle_error

_logger = logger(__name__)


def send_message(to: str, message: str) -> Optional[dict]:
    """
    Send a text message via WhatsApp
    
    Args:
        to: Recipient phone number
        message: Text message to send
        
    Returns:
        Response data if successful, None otherwise
    """
    url = f"{API_BASE}/messages"
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    try:
        response = requests.post(url, headers=get_headers(), json=data)
        _logger.info("Message send response: %s", response.status_code)
        
        resp_data = None
        try:
            resp_data = response.json()
        except Exception as e:
            _logger.error(f"Exception: {e}")
            _logger.error("Response not valid JSON: %s", response.text)

        if response.ok:
            _logger.info("Message sent successfully to %s", to)
            _logger.debug("Response JSON: %s", resp_data)
            return resp_data
        else:
            _logger.error("Failed to send message. Status: %s", response.status_code,f"\n Payload: {json.dumps(data, indent=2)}")
            _logger.error("Error response: %s", json.dumps(resp_data, indent=2))
            return resp_data

    except requests.RequestException as e:
        _logger.exception("HTTP request failed: %s", str(e))
        return None


def typing_indicator(msg_id: str) -> bool:
    """
    Send a typing indicator for a message
    
    Args:
        msg_id: Message ID to mark as read with typing indicator
        
    Returns:
        True if successful, False otherwise
    """
    url = f"{API_BASE}/messages"
    data = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": msg_id,
        "typing_indicator": {
            "type": "text"
        }
    }

    try:
        response = requests.post(url, headers=get_headers(), json=data)
        _logger.info("Typing indicator response: %s", response.status_code)

        if response.ok:
            _logger.info("Typing indicator sent for message %s", msg_id)
            _logger.debug("Response JSON: %s", response.json())
            return True

        _logger.error("Failed to send typing indicator. Status: %s", response.status_code)
        try:
            error_obj = response.json()
            _logger.error("Error response: %s", json.dumps(error_obj, indent=2))
            handle_error(error_obj)
        except ValueError:
            _logger.error("Response not valid JSON: %s", response.text)
        return False

    except requests.RequestException as e:
        _logger.exception("Failed to send typing indicator: %s", str(e))
        return False
