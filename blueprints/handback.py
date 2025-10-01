from flask import Blueprint, request, jsonify
from config import logger
from db import engine, conversation
from sqlalchemy import select, update
from bot import graph
import json
handback_bp = Blueprint('handback', __name__)
_logger = logger(__name__)

@handback_bp.route("/handback", methods=["GET","POST"])  
def handback_to_ai():
    """Hand conversation back to AI"""
    if request.method == "POST":
        data = request.get_json(force = True)

        _logger.info(f"DATA RECEIVED: {json.dumps(data, indent=2)}")

        # print(f" DATA RECEIVED: {data}, {type(data)}")

        # if data: 
        #     return "OK", 200
        # else:
        #     return "FAILED", 500
        if not data or "phone" not in data:
            return jsonify({"status": "error", "message": "Missing phone"}), 400
        phone = data["phone"]
        
        try:
            with engine.begin() as conn:
                # Clear intervention flag
                conn.execute(
                    update(conversation)
                    .where(conversation.c.phone == str(phone))
                    .values(human_intervention_required=False)
                )
                
                # Update LangGraph state
                config = {"configurable": {"thread_id": phone}}
                graph.update_state(config, {"operator_active": False})
                
            return jsonify({"status": "handback_complete"})
            
        except Exception as e:
            _logger.error(f"Handback failed: {e}")
            return jsonify({"status": "error"}), 500
        
    elif request.method == "GET":
        return "THIS ENDPOINT IS UP AND RUNNING"