import time
from utility.whatsapp import send_media
from config import logger
from db import engine, conversation, message, sample_library
from sqlalchemy import select, insert
import json
from datetime import datetime

_logger = logger(__name__)

def send_media_tool(media_description: str, user_ph, caption = "") -> dict:
    responses = []

    with engine.begin() as conn:
        result = conn.execute(
        select(sample_library.c.media_id, sample_library.c.media_file_type)
        .where(sample_library.c.media_description == media_description)
    )
        rows = result.mappings().all()

    for row in rows:
        try:

            time.sleep(1)
            response = send_media(row["media_file_type"], str(user_ph), row["media_id"])
            _logger.info(f"Send Media Response: {response}")
        except Exception as e:
            _logger.error(f"Failed to send media, media id: {row['media_id']}")

            return {"response": str(e)}

        with engine.begin() as conn:
            try:
                conversation_id = None
                result_set = conn.execute(select(conversation.c.id).where(conversation.c.phone == str(user_ph)))
                conversation_ids = result_set.mappings().first()

                if conversation_ids:
                    conversation_id = conversation_ids['id']

                mime_type = None
                media_type = row["media_file_type"]
                if media_type == "image":
                    mime_type = "image/jpeg"
                elif media_type == "video":
                    mime_type = "video/mp4"
                elif media_type == "audio":
                    mime_type = "audio/ogg" 

                rows = {
                    "conversation_id": conversation_id,
                    "direction": "outbound",
                    "sender_type": "ai",
                    "external_id": response['messages'][0]['id'],
                    "has_text": True if len(caption)>0 else False,
                    "message_text": caption if len(caption)>0 else None,
                    "media_info": json.dumps({"id": str(row['media_id']), "mime_type": mime_type, "description":"NO DESCRIPTION"}),
                    "status": "pending", #To be changed later
                    "provider_ts": datetime.utcnow().isoformat()
                }

                conn.execute(insert(message).values(rows))
                _logger.info(f"Media_sent and DB entry made for media id: {row['media_id']}")

                responses.append(response)
            except Exception as e:

                _logger.error(f"DB Transaction failed while entering media info in the DB, EXCEPTION OCCURED: {str(e)}")

                responses.append(response)

    return {"results": responses}
