import os
from glob import glob
from config import DB_URL, logger
from db import pool
from whatsapp import upload_video

_logger = logger(__name__)


def refactor_dict(data: dict) -> dict: 
    if "entry" not in data: return {"Error": "data not valid"}
    
    value = data["entry"][0]["changes"][0]["value"]

    # Inbound message
    if "messages" in value and "contacts" in value:
        metadata = value["metadata"]
        user_ph = value["contacts"][0]["wa_id"]
        user_name = value["contacts"][0]["profile"]["name"]
        msg_id = value["messages"][0]["id"]
        category = value["messages"][0]["type"]
        
        if category == "text":
            message = value["messages"][0]["text"]["body"]
            return {
            "class": "text",
            "category": None,
            "type": "inbound",
            "timestamp": value["messages"][0]["timestamp"],
            "metadata": metadata,
            "from": {
                "phone": user_ph,
                "name": user_name,
                "message_id": msg_id,
                "message": message,
                },
            }
        elif category in ["audio", "image", "video"]:
            media = value["messages"][0]["image"] if category == "image" else value["messages"][0]["audio"]
            mime_type = media["mime_type"]
            media_id = media["id"]
            return {
            "class": "media",
            "category": category,   
            "type": "inbound",
            "timestamp": value["messages"][0]["timestamp"],
            "metadata": metadata,
            "from":{
                "phone": user_ph,
                "name": user_name,
                "message_id": msg_id,
                "mime_type": mime_type,
                "media_id": media_id,
                }
            }
        
        else:
            _logger.error("Received data format not supported!")
            logger.info(f"Data received: {data}")
            return {
                "class": category,
                "category": None,
                "type": "inbound",
                "metadata": metadata,
                "from":{
                    "phone": user_ph,
                    "name": user_name,
                    "message_id": msg_id,
                }
            }
       
    # Delivery status
    if "statuses" in value:
        return {
            "type": "status",
            "id": value['statuses'][0]["id"],
            "status": value['statuses'][0]['status'],    
            "metadata": value.get("metadata", {}),
        }

    return {"Error": "unhandled payload", "raw": value}

def db_saver():
    files = [
    glob("/home/darkus/Desktop/whatsapp-ai-bot/media/Anniversary/*"),
    glob("/home/darkus/Desktop/whatsapp-ai-bot/media/Birthday/*"),
    glob("/home/darkus/Desktop/whatsapp-ai-bot/media/wedding/2D Sample/*"),
    glob("/home/darkus/Desktop/whatsapp-ai-bot/media/wedding/2D Sample with Caricature/*"),
    glob("/home/darkus/Desktop/whatsapp-ai-bot/media/wedding/3D Sample with Caricature/*"),
    ]

    for file_group in files:
        for f in file_group:
            try:
                media_id = upload_video(f)
                media_name = os.path.basename(f)

                # detect type
                media_type = next((t for t in ["anniversary", "birthday", "wedding"] if t in f.lower()), "")

                # detect description
                desc = next(
                    (d for d in [
                        "2d sample",
                        "2d sample with caricature",
                        "3d sample with caricature"
                    ] if d in f.lower()),
                    "2d with caricature"
                )

                print(f"Name: {media_name}, ID: {media_id}, Type: {media_type}, Description: {desc}")

                with pool.connection() as conn:
                    conn.autocommit=True
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO sample_media_library (media_name, media_id, media_type, media_description)
                            VALUES (%s, %s, %s, %s);
                        """, (media_name.lower(), str(media_id), media_type.lower(), desc.lower()))
                    conn.commit()

            except Exception as e:
                _logger.error("Error processing file %s: %s", f, e)

    print("Operation Done!")
 

def search_db_tool(media_type:str, media_description: str) -> list:
    id_list = []
    with pool.connection() as conn:
        with conn.cursor() as curr:
            sql_query = """SELECT media_id FROM sample_media_library WHERE media_type = %s AND media_description = %s"""
            curr.execute(sql_query, (media_type.lower(), media_description.lower()))
            result = curr.fetchall()

    for row in result:
        id_list.append(row[0])
    
    return id_list;



