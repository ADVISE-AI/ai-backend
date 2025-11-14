""" Tool for Gemini to request manual takeover when it cannot handle a user query."""
from db import engine, conversation
from sqlalchemy import select, update
import requests
from config import logger, AI_BACKEND_URL

_logger = logger(__name__)


def callIntervention(state, user_ph: str):
    if state.get("operator_active"):
        return

    try:
        with engine.begin() as conn:
            row = conn.execute(
                select(conversation.c.human_intervention_required).where(
                    conversation.c.phone == str(user_ph)
                )
            ).mappings().first()

            already_required = row and row["human_intervention_required"]

            if not already_required:
                # Call operator notification service
                response = requests.post(
                    f"{AI_BACKEND_URL}/api/v1/takeover", json={"phone": user_ph}
                )
                response = response.json()
                
                if response["status"] == "takeover_complete":
                    _logger.info(f"Intervention requested for {user_ph}")
                    return response
                else:
                    _logger.warning(
                        f"Intervention request failed for {user_ph}, status={response.status_code}"
                    )

    except Exception as e:
        _logger.error(f"RequestIntervention failed for {user_ph}: {e}")

    return