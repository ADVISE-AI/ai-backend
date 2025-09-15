from flask import Flask, request, jsonify
from config import VERIFY_TOKEN, logger
from whatsapp import send_message, typing_indicator, download_media, get_url
from utils import refactor_dict
from bot import stream_graph_updates
from db import engine, user_conversation, conversation, message
from sqlalchemy import select, insert, update, delete
from time import localtime, strftime
from datetime import datetime
import os
import time
import json

    
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY")

if not APP_SECRET_KEY:
    raise EnvironmentError("Missing Secrect Key")

app = Flask(__name__)
app.secret_key = APP_SECRET_KEY

_logger = logger(__name__)


@app.route("/webhook", methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        data = request.get_json()
        
        abstracted_data = refactor_dict(data)

        if abstracted_data["type"] == "inbound":
            
            _class = abstracted_data['class']

            _from = abstracted_data['from']
            user_ph = _from['phone']
            user_name = _from['name']
            msg_id = _from["message_id"]
            
            timestamp = abstracted_data['timestamp']

            msg = None
            has_text = None
            media_info = None

            responded = None
            if _class == "text":
                text = _from["message"]
                has_text = True

                if abstracted_data["context"] is not None:
                    with engine.begin() as conn:
                        result = conn.execute(select(message.c.media_info).where(message.c.external_id == str(abstracted_data["context"]["id"])))

                        media_info = result.first()
                        media_id = json.loads(media_info[0])["id"]

                        media_data = download_media(media_id)

                        msg = {
                            "context": True,
                            "data": media_data['data'], 
                            "mime_type": media_data["mime_type"],
                            "category": "video",
                            "message": text
                        }
                else:
                    msg = text
                
            elif _class == "media":
                
                dl_content = download_media(_from['media_id'])
                msg = {
                    "context": False,
                    "data": dl_content['data'], 
                    "category":abstracted_data['category'],
                    "content_type": dl_content['content_type'],
                    "mime_type": _front["mime_type"],
                }

                media_info = {"id": _from['media_id'], "mime_type": msg["mime_type"], "description": ""}

                has_text = True 
            
            with engine.begin() as conn:
                try:
                    result_set = conn.execute(
                        select(conversation.c.id).where(conversation.c.phone == str(user_ph))
                    )
                    conv = result_set.mappings().first()

                    if conv:  
                        conv_id = conv["id"]

                        row = {
                            "conversation_id": conv_id,
                            "direction": "inbound",
                            "sender_type": "customer",
                            "external_id": str(msg_id),
                            "has_text": has_text,
                            "message_text": msg if isinstance(msg, str) else None,
                            "media_info": json.dumps(media_info) if media_info else None,
                            "provider_ts": datetime.fromtimestamp(int(timestamp)),
                        }
                        result = conn.execute(insert(message).values(row))
                        new_msg_id = result.inserted_primary_key[0]

                        conn.execute(
                            update(conversation)
                            .where(conversation.c.id == conv_id)
                            .values(last_message_id=new_msg_id)
                        )

                    else:
                        result = conn.execute(
                            insert(conversation)
                            .values({"phone": user_ph, "name": user_name})
                            .returning(conversation.c.id)
                        )
                        conv_id = result.scalar_one()

                        row = {
                            "conversation_id": conv_id,
                            "direction": "inbound",
                            "sender_type": "customer",
                            "external_id": str(msg_id),
                            "has_text": has_text,
                            "message_text": msg if isinstance(msg, str) else None,
                            "media_info": json.dumps(media_info) if media_info else None,
                            "provider_ts": datetime.fromtimestamp(int(timestamp)),
                        }
                        result = conn.execute(insert(message).values(row))
                        new_msg_id = result.inserted_primary_key[0]

                        conn.execute(
                            update(conversation)
                            .where(conversation.c.id == conv_id)
                            .values(last_message_id=new_msg_id)
                        )

                except Exception as e:
                    _logger.error(f"Database insert failed (inbound): {str(e)}")


            respond_to_user(msg, user_ph, msg_id)
            _logger.info("Response sent on Whatsapp.")


        elif abstracted_data["type"] == "statuses":
            with engine.begin() as conn:
                try:
                    result_set = conn.execute(select(message).where(message.c.external_id == str(abstracted_data["id"])))
                    msg_id = result_set.mappings().all()
                except Exception as e:
                    _logger.error("ERROR In getting Message ID for updating status")
                if msg_id:
                    _logger.info(f"Statues update: Message ID: {abstracted_data['id']}")
                    try:
                        conn.execute(update(message).values({"status": f"{abstracted_data['status']}"}).where(message.c.external_id == msg_id))
                    except Exception as e:
                        _logger.error(f"Status update failed; Exception: {str(e)}")

        return "OK", 200


    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        challenge = request.args.get('hub.challenge')
        token = request.args.get('hub.verify_token')
        _logger.info(f"mode: {mode}, challenge: {challenge}, token: {token}")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            _logger.info("WEBHOOK VERIFIED")
            return challenge
        else:
            _logger.warning(f"Invalid Token: {token}")
            return "Invalid Token", 403



def respond_to_user(user_input, user_ph: str, message_id: str):
    try:
        with engine.begin() as conn:
            result_set = conn.execute(select(conversation.c.id).where(conversation.c.phone == str(user_ph)))
            conversation_ids = result_set.mappings().first()
            if conversation_ids:
                conversation_id = conversation_ids['id']
                ai_resp = stream_graph_updates(user_ph, user_input)
                ai_resp_message = ai_resp.get("content")
                ai_resp_metadata = ai_resp.get("metadata")

                typing_indicator(message_id)
                time.sleep(5)

                if ai_resp_message and ai_resp_message.strip():
                     response = send_message(user_ph, ai_resp_message)

                     try: 
                        msg_id = response["messages"][0]['id'] if response else None
                        has_text = True
                        msg = ai_resp_message
                        timestamp = datetime.utcnow().isoformat()

                        rows = {
                            "conversation_id": conversation_id,
                            "direction": "outbound", 
                            "sender_type": "ai", 
                            "external_id": str(msg_id),
                            "has_text": has_text, 
                            "message_text": msg if msg and type(msg) is str else None,
                            "provider_ts": timestamp
                        }

                        conn.execute(insert(message).values(rows))
                     except Exception as e:
                        _logger.error(f"Database insert Failed in {respond_to_user.__name__}. ERROR CAUSE: {e}")

                return {
                     "User_Data": {
                         "Phone": user_ph,
                         "message": user_input,
                         "message_id": message_id
                     },
                     "AI_Response": ai_resp_message,
                     "Metadata": ai_resp_metadata
                 }
            else:
                _logger.error(f"No conversation id found for the user phone: {user_ph}")

    except Exception as e:
        _logger.error(f"DB Connection failed: Exception: {e}")

   

@app.route("/media") #/media?id=982173129837
def media_url():
    media_id = str(request.args.get('id'))
    return jsonify(get_url(media_id))
