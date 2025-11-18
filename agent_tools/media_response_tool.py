import time
from utility.whatsapp import send_media
from config import logger
from db import engine, conversation, message, media_files, categories
from sqlalchemy import select, or_
import json
from datetime import datetime

_logger = logger(__name__)

def send_media_tool(category: str, subcategory: str, user_ph: str, caption="") -> dict:
    _logger.info(f"[MEDIA TOOL] Called with category='{category}', subcategory='{subcategory}', user_ph={user_ph}")
    responses = []


    category_like = f"%{category.lower()}%"
    sub_cat_like = f"%{subcategory.lower()}%" if subcategory else None

    with engine.begin() as conn:
        base_query = (
            select(
                media_files.c.id.label("media_id"),
                media_files.c.wa_media_id,
                media_files.c.file_type,
                media_files.c.file_extension,
            )
            .select_from(media_files.join(categories, media_files.c.category_id == categories.c.id))
            .where(
                categories.c.name.ilike(category_like)
            )
        )

        # If subcategory provided → filter
        if sub_cat_like:
            base_query = base_query.where(media_files.c.subcategory.ilike(sub_cat_like))

        result = conn.execute(base_query)
        rows = result.mappings().all()

    if not rows:
        _logger.warning(f"No media for category '{category}' subcategory '{subcategory}'")
        return {"results": [], "message": "No media found"}

    for row in rows:
        wa_id = row["wa_media_id"]

        try:
            time.sleep(1)
            response = send_media(row["file_type"], str(user_ph), wa_id)
            _logger.info(f"Sent WA media ID: {wa_id}")

        except Exception as e:
            _logger.error(f"Failed to send WA media ID {wa_id}: {str(e)}")
            return {"response": str(e)}

        # Insert into DB
        with engine.begin() as conn:
            try:
                conv_row = conn.execute(
                    select(conversation.c.id).where(conversation.c.phone == str(user_ph))
                ).mappings().first()

                conversation_id = conv_row["id"] if conv_row else None

                mime = resolve_mime(row["file_type"], row["file_extension"])

                payload = {
                    "conversation_id": conversation_id, 
                    "direction": "outbound",
                    "sender_type": "ai",
                    "external_id": response['messages'][0]['id'],
                    "has_text": True if caption else False,
                    "message_text": caption if caption else None,
                    "media_info": json.dumps({
                        "media_id": wa_id,
                        "mime_type": mime,
                        "category": category,
                        "subcategory": subcategory or None,
                    }),
                    "status": "pending",
                    "provider_ts": datetime.utcnow().isoformat(),
                }

                conn.execute(message.insert().values(payload))
                _logger.info(f"DB logged for WA ID: {wa_id}")

                responses.append(response)

            except Exception as e:
                _logger.error(f"DB log failed for WA ID {wa_id}: {e}")
                responses.append(response)

    return {"results": responses}

def resolve_mime(file_type: str, ext: str):
    if file_type == "image":
        return "image/jpeg"
    if file_type == "video":
        return "video/mp4"
    if file_type == "audio":
        return "audio/ogg"
    return f"application/{ext}"
