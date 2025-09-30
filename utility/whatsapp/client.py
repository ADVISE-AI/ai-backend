"""
WhatsApp API Client - Object-oriented interface
"""

from typing import Optional, Dict
from . import messaging, media


class WhatsAppClient:
    """
    High-level client for WhatsApp Business API
    
    Example:
        client = WhatsAppClient()
        client.send_text("+1234567890", "Hello!")
        media_id = client.upload_video("video.mp4")
        client.send_video("+1234567890", media_id, "Check this out!")
    """
    
    def send_text(self, to: str, message: str) -> Optional[dict]:
        """Send a text message"""
        return messaging.send_message(to, message)
    
    def send_typing_indicator(self, msg_id: str) -> bool:
        """Send typing indicator"""
        return messaging.typing_indicator(msg_id)
    
    def upload_video(self, file_path: str) -> Optional[str]:
        """Upload a video and return media ID"""
        return media.upload_video(file_path)
    
    def send_video(self, to: str, media_id: str, caption: str = "") -> dict:
        """Send a video"""
        return media.send_media("video", to, media_id, caption)
    
    def send_image(self, to: str, media_id: str, caption: str = "") -> dict:
        """Send an image"""
        return media.send_media("image", to, media_id, caption)
    
    def send_audio(self, to: str, media_id: str) -> dict:
        """Send audio"""
        return media.send_media("audio", to, media_id)
    
    def download_media(self, media_id: str) -> Optional[Dict]:
        """Download media content"""
        return media.download_media(media_id)
    
    def get_media_url(self, media_id: str) -> Optional[Dict]:
        """Get download URL for media"""
        return media.get_url(media_id)
