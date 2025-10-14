from flask import Blueprint, request
from config import logger, VERIFY_TOKEN
from utility import normalize_webhook_payload, is_duplicate, get_message_buffer
from tasks import update_message_status_task, check_buffer_task
import time
import json

webhook_bp = Blueprint('webhook', __name__)
_logger = logger(__name__)

message_buffer = get_message_buffer()

@webhook_bp.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        data = request.get_json()
        _logger.info(f"RECEIVED WHATSAPP WEBHOOK DATA: {json.dumps(data, indent = 2)}")

        normalized_data = normalize_webhook_payload(data)

        if normalized_data["type"] == "inbound":

            if is_duplicate(normalized_data["from"]["message_id"], normalized_data["from"]["phone"]):
                   _logger.info(f"Duplicate message {normalized_data['from']['message_id']} ignored")
                   return "OK", 200
            
            is_first_message = message_buffer.add_message(normalized_data["from"]["phone"], normalized_data)

            if is_first_message:
                # Schedule buffer check after debounce time
                _logger.info(f"Scheduling buffer check for {normalized_data['from']['phone']} in 3 seconds")
                check_buffer_task.apply_async(
                    args=[normalized_data['from']['phone']],
                    countdown=10,  # Check after 3 seconds
                    queue='messages',
                    priority=5
                )
            
            return "OK", 200

        elif normalized_data["type"] == "status":
            _logger.info(f"Message status update received: {json.dumps(normalized_data, indent=2)}")
            status_msg_id = normalized_data.get('id', 'unknown')
            status = normalized_data.get('status', 'unknown')
                           
            try:
                _logger.info(f"Message Status update {status_msg_id} ➔ {status}")

                start_time = time.time()
                update_message_status_task.apply_async(args=[normalized_data], queue='status', priority=2)

                response_time = (time.time() - start_time) * 1000
                _logger.info(f"WEBHOOK: Status acknowledged in {response_time:.0f}ms")
            except Exception as e:
                _logger.error(f"Failed to queue status update: {e}")
            
            return "OK", 200
        
        else:
            msg_type = normalized_data.get("type", "unknown")
            _logger.warning(f"Unknown message type received: {msg_type}")
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