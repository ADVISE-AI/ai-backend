from flask import Blueprint, request, jsonify
from config import logger
from db import engine, conversation
from sqlalchemy import select, update
from tasks import update_langgraph_state_task
import json

handback_bp = Blueprint('handback', __name__)
_logger = logger(__name__)

@handback_bp.route("/handback", methods=["GET", "POST"])  
def handback_to_ai():
    """Hand conversation back to AI"""
    if request.method == "POST":
        data = request.get_json(force=True)
        _logger.info(f"DATA RECEIVED: {json.dumps(data, indent=2)}")

        if not data or "phone" not in data:
            return jsonify({"status": "error", "message": "Missing phone"}), 400
        
        phone = data["phone"]
        
        try:
            with engine.begin() as conn:
                conn.execute(
                    update(conversation)
                    .where(conversation.c.phone == str(phone))
                    .values(human_intervention_required=False)
                )
                _logger.info(f"Intervention flag cleared for {phone}")
            
            # CRITICAL FIX: Offload LangGraph update to Celery
            # This prevents blocking the Gunicorn worker
            update_langgraph_state_task.apply_async(
                args=[phone, {"operator_active": False}],
                queue='state',
                priority=8  # High priority for state updates
            )
            _logger.info(f"Queued LangGraph state update for {phone}")
            
            return jsonify({"status": "handback_complete"})
            
        except Exception as e:
            _logger.error(f"Handback failed: {e}", exc_info=True)
            return jsonify({"status": "error"}), 500
        
    elif request.method == "GET":
        return "THIS ENDPOINT IS UP AND RUNNING"