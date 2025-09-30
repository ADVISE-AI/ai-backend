from config import logger

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
        context = value["messages"][0]["context"] if "context" in value["messages"][0] else None

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
            "context": context            
            }


        elif category in ["audio", "image", "video"]:
            if category == "image":
                media = value["messages"][0]["image"]
            elif category == "audio":
                media = value["messages"][0]["audio"]
            else:  # video
                media = value["messages"][0]["video"]

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
                "message": media["caption"] if "caption" in media else None
                },
            "context": context
            }
        
        else:
            _logger.error("Received data format not supported!")
            _logger.info(f"Data received: {data}")
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