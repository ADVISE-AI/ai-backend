"""
Error handling utilities for WhatsApp API
"""

from typing import Dict
from config import logger
from .constants import ERROR_MAPPINGS

_logger = logger(__name__)


def handle_error(error_obj: Dict) -> None:
    """
    Handles and logs WhatsApp API errors
    
    Args:
        error_obj: Error response object from API
    """
    error = error_obj.get("error", {})
    error_code = error.get("code")
    error_message = error.get("message", "Unknown error")

    message = ERROR_MAPPINGS.get(error_code, f"Unknown error code: {error_code}")
    _logger.error(f"Error {error_code}: {message} - {error_message}")
