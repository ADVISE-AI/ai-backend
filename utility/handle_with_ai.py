from config import logger
from db import engine, message
from sqlalchemy import insert, select
from datetime import datetime
from bot import stream_graph_updates
from .whatsapp import send_message, typing_indicator, download_media
import json
import time


_logger = logger(__name__)

def handle_with_ai(clean_data: dict, conversation_id):
    """Process user message with AI and store both user and AI messages"""
    
    user_input = user_input_builder(clean_data)
    ai_response = stream_graph_updates(clean_data["from"]["phone"], user_input)

    ai_message = ai_response.get("content")
    ai_metadata = ai_response.get("metadata")

    typing_indicator(clean_data["from"]["message_id"])
    time.sleep(5)

    response = send_message(clean_data["from"]["phone"], ai_message)

    with engine.begin() as conn:
        row = {
            "conversation_id": conversation_id,
            "direction": "outbound",
            "sender_type": "ai",
            "external_id": response["messages"][0]['id'],
            "has_text": True,
            "message_text": ai_message,
            "provider_ts": datetime.fromtimestamp(int(time.time())),
            "extra_metadata": ai_metadata
        }

        try:
            conn.execute(insert(message).values(row))
        except Exception as e:
            _logger.error(f"Failed to insert in DataBase: {e}")


def user_input_builder(clean_data: dict) -> dict:
    user_input = {}
    if clean_data["class"] == "text":
        if clean_data["context"]:
                with engine.begin() as conn:
                    result = conn.execute(select(message.c.message_text, message.c.media_info).where(message.c.external_id == clean_data["context"]["id"]))
                    row = result.mappings().first()
                if row and row["media_info"]:
                    media_info = json.loads(row["media_info"])
                    downloaded_data =  download_media(media_info["id"])
                    user_input =  {
                                "context": True,
                                "context_type": "media",
                                "data": downloaded_data['data'], 
                                "category": "image" if media_info["mime_type"].startswith("image/") else "video" if media_info["mime_type"].startswith("video/") else "audio" if media_info["mime_type"].startswith("audio/") else "file",
                                "content_type": downloaded_data['content_type'],
                                "mime_type": downloaded_data['mime_type'],
                                "message": clean_data["from"]["message"]
                            }
                    
                elif row["message_text"]:
                    user_input = {
                        "context": True,
                        "context_type": "text",
                        "context_message": row["message_text"],
                        "message": clean_data["from"]["message"]
                    }
                
        else:
            user_input = {
                "context": False,
                "class": "text",
                "message": clean_data["from"]["message"]
            }
    elif clean_data["class"] == "media":
        downloaded_data =  download_media(clean_data["from"]["media_id"])
        user_input =  {
                    "context": False,
                    "class": "media",
                    "data": downloaded_data['data'], 
                    "category": clean_data['category'],
                    "content_type": downloaded_data['content_type'],
                    "mime_type": downloaded_data['mime_type'],
                    "message": clean_data["from"].get("message")
                }
        
    return user_input