from flask import Blueprint, request
from config import logger, VERIFY_TOKEN
from utility import normalize_webhook_payload, is_duplicate, message_router, get_message_buffer
from tasks import process_message_task, update_message_status_task
import time
import json

webhook_bp = Blueprint('webhook', __name__)
_logger = logger(__name__)

message_buffer = get_message_buffer(callback=message_router)

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
            
            message_buffer.add_message(normalized_data["from"]["phone"], normalized_data)

            try:
                _logger.info(f"Queueing message {normalized_data}")
                start_time = time.time()
                task = process_message_task.apply_async(args=[normalized_data], queue='messages', priority = 5, retry = True, retry_policy = { 
                    'max_retries': 3, 
                    'interval_start': 5,
                    'interval_step': 10,
                    'interval_max': 60,
                })

                response_time = (time.time() - start_time) * 1000
                _logger.info(f"Task {task.id} queued for message {task.id[:8]} in {response_time:.2f} ms")

            except Exception as e:
                _logger.error(f"Failed to queue task for message {normalized_data['from']['message_id']}: {e}", exc_info=True)
            
            return "OK", 200
            

        elif normalized_data["type"] == "status":
            _logger.info(f"Message status update received: {json.dumps(normalized_data, indent=2)}")
            status_msg_id = normalized_data.get('id', 'unknown')
            status = normalized_data.get('status', 'unknown')
                
            _logger.info(f"Message Status update {status_msg_id} -> {status}")
                
            try:
                update_message_status_task.apply_async(
                args=[normalized_data],
                queue='status',
                priority=2
                )

            except Exception as e:
                _logger.error(f"Failed to queue status update: {e}")
            
            response_time = (time.time() - start_time) * 1000
            _logger.info(f"✅ WEBHOOK: Status acknowledged in {response_time:.0f}ms")
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