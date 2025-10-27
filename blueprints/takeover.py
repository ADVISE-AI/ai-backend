from flask import Blueprint, request, jsonify
from config import logger
from db import engine, conversation
from sqlalchemy import select, update
from tasks import update_langgraph_state_task
import json

takeover_bp = Blueprint('takeover', __name__)
_logger = logger(__name__)

@takeover_bp.route("/takeover", methods=["GET", "POST"])  
def takeover_by_human():
    """Takeover conversation by human agent"""
    if request.method == "POST":
        data = request.get_json(force=True)
        
        _logger.info(f"DATA RECEIVED: {json.dumps(data, indent=2)}")

        if not data or "phone" not in data:
            return jsonify({"status": "error", "message": "Missing phone"}), 400

        phone = data["phone"]

        try:
            _logger.info(f"Setting intervention flag for {phone}")
            with engine.begin() as conn:
                # Set intervention flag in DB
                conn.execute(
                    update(conversation)
                    .where(conversation.c.phone == str(phone))
                    .values({"human_intervention_required": True})
                )
                _logger.info(f"Intervention flag set for {phone}")
            
            # CRITICAL FIX: Offload LangGraph update to Celery
            # This prevents blocking the Gunicorn worker
            update_langgraph_state_task.apply_async(
                args=[phone, {"operator_active": True}],
                queue='state',
                priority=8  # High priority for state updates
            )
            _logger.info(f"Queued LangGraph state update for {phone}")
            
            return jsonify({"status": "takeover_complete"}), 200
            
        except Exception as e:
            _logger.error(f"Takeover failed: {e}", exc_info=True)
            return jsonify({"status": "error"}), 500
        
    elif request.method == "GET":
        return "THIS ENDPOINT IS UP AND WORKS", 200