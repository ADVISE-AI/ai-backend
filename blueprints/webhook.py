from flask import Blueprint, request
from config import logger, VERIFY_TOKEN
from utility import refactor_dict, is_duplicate_message, message_router
import json

webhook_bp = Blueprint('webhook', __name__)
_logger = logger(__name__)

@webhook_bp.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        data = request.get_json()
        _logger.info(f"RECEIVED WHATSAPP WEBHOOK DATA: {json.dumps(data, indent = 2)}")

        clean_data = refactor_dict(data)

        if clean_data["type"] == "inbound":

            if is_duplicate_message(clean_data["from"]["message_id"], clean_data["from"]["phone"]):
                   _logger.info(f"Duplicate message {clean_data['from']['message_id']} ignored")
                   return "OK", 200
               
            message_router(clean_data)
        
        elif clean_data["type"] == "status":
            _logger.info(f"Message status update received: {json.dumps(clean_data, indent=2)}")
            pass

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