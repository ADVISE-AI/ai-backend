"""
Configuration and constants for WhatsApp API client
"""

from config import WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, WHATSAPP_GRAPH_URL

# API Configuration
BASE_URL = WHATSAPP_GRAPH_URL
API_BASE = WHATSAPP_GRAPH_URL + WHATSAPP_PHONE_NUMBER_ID

# Error code mappings
ERROR_MAPPINGS = {
    0: "AuthException. Get a new access token.",
    3: "Failed API method. Check app permissions.",
    10: "Permission denied.",
    190: "Access token expired.",
    368: "Temporarily blocked due to policy violations.",
}

def get_headers():
    """Returns the authorization headers for API requests"""
    return {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

def get_auth_header():
    """Returns only the authorization header (for file uploads)"""
    return {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
