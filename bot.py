from typing import Annotated, List 
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END 
from langgraph.graph.message import AnyMessage, add_messages
# from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
# from langchain_core.messages import SystemMessage
from langgraph.prebuilt import ToolNode, InjectedState
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres import PostgresSaver
from config import OPENAI_API_KEY, GOOGLE_API_KEY, DB_URL, logger
from whatsapp import send_media
from utils import search_db_tool
from pydantic import BaseModel, Field
from db import engine, message, conversation
from sqlalchemy import insert, select
from psycopg import Connection
from datetime import datetime
import json
import base64
import requests
import hashlib
import time
_logger = logger(__name__)


langgraph_conn = Connection.connect(f"postgresql://{DB_URL}", autocommit = True)

try:
    checkpointer = PostgresSaver(langgraph_conn)
    checkpointer.setup()
    _logger.info("Langgraph DB setup successfully")
except Exception as e:
    _logger.error("Langgraph DB setup Failed")
    _logger.info(f"Error Info: {str(e)}")


class State(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]

@tool("RespondWithMedia")
def RespondWithMedia(send: bool = True, caption: str = "", *,config: RunnableConfig) -> dict:
    """
    Send the user WhatsApp media based on file type.
    Args:
        send_all_samples: If True, sends video, image, and audio samples
        
    """

    media_types = ["video", "image", "audio"]
    user_ph = config.get("configurable", {}).get("thread_id")
    responses = []
    
    for media_type in media_types:
        id_list = search_db_tool(str(media_type))
        for id in id_list:
            try:
                time.sleep(1)
                response = send_media(str(media_type), str(user_ph), id)
                _logger.info(f"Send Media Response: {response}")

            except Exception as e:
                _logger.error(f"Failed to send media, media id: {id}")
                return {"response": str(e)}

            with engine.begin() as conn:
                try:
                    conversation_id = None
                    result_set = conn.execute(select(conversation.c.id).where(conversation.c.phone == str(user_ph)))
                    conversation_ids = result_set.mappings().first()

                    if conversation_ids:
                        conversation_id = conversation_ids['id']
                    mime_type = None
                    if media_type == "image":
                        mime_type = "image/jpeg"
                    elif media_type == "video":
                        mime_type = "video/mp4"
                    elif media_type == "audio":
                        mime_type = "audio/ogg" 
                    rows = {
                        "conversation_id": conversation_id,
                        "direction": "outbound",
                        "sender_type": "ai",
                        "external_id": response['messages'][0]['id'],
                        "has_text": True if len(caption)>0 else False,
                        "message_text": caption if len(caption)>0 else None,
                        "media_info": json.dumps({"id": str(id), "mime_type": mime_type, "description":"NO DESCRIPTION"}),
                        "status": "pending", #To be changed later
                        "provider_ts": datetime.utcnow().isoformat()
                    }
                    conn.execute(insert(message).values(rows))
                    _logger.info(f"Media_sent and DB entry made for media id: {id}")
                    responses.append(response)
                except Exception as e:
                    _logger.error(f"DB Transaction failed while entering media info in the DB, EXCEPTION OCCURED: {str(e)}")
                    responses.append(response)



    return {"results": responses}


prompt_template = ChatPromptTemplate.from_messages([
    ("system", "{system_message}"), 
    MessagesPlaceholder("messages")
])


gemini =  init_chat_model("google_genai:gemini-2.5-flash")

gemini_with_tools = gemini.bind_tools([RespondWithMedia])
gemini_agent = prompt_template | gemini_with_tools
with open("gemini_system_prompt.txt", "r") as f1:
    GEMINI_SYSTEM_PROMPT = f1.read()
    
def gemini_node(state: State):
    ai_resp = gemini_agent.invoke({
        "system_message": GEMINI_SYSTEM_PROMPT,
        "messages": state['messages']  # Use truncated history
    })

    return {
        "messages": [ai_resp],
    }



def isToolCall(state: State):
    """Check if Gemini called any tools"""
    last_message = state['messages'][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tool_call"
    else:
        return "no_tool_call"

graph_builder = StateGraph(State)
graph_builder.add_node("gemini", gemini_node)
graph_builder.add_node("tools", ToolNode([RespondWithMedia]))
graph_builder.add_edge(START, "gemini")
graph_builder.add_conditional_edges("gemini", isToolCall, {
    "tool_call": "tools",
    "no_tool_call": END   
})
graph_builder.add_edge("tools", END)
graph_builder.add_edge("gemini", END) 


graph = graph_builder.compile(checkpointer = checkpointer)

DEFAULT_STATE = {
    "messages": [{"role": "user", "content": None}],
}

def stream_graph_updates(user_ph: str, user_input) -> dict:
    final_response = {"content": "", "metadata": None}
    content = None
    config = {"configurable": {"thread_id": user_ph}}
    
    if isinstance(user_input, dict) and user_input.get("context") is False:
        category = user_input["category"]
        data_string = base64.b64encode(user_input["data"]).decode("utf-8")
        mime_type = user_input["mime_type"]
        
        content_block = None
        if category == "image":
            if not mime_type.startswith("image/"):
                _logger.warning(f"Invalid image MIME type: {mime_type}, defaulting to image/jpeg")
                mime_type = "image/jpeg"
            content_block = {
                "type": "image_url", 
                "image_url": f"data:{mime_type};base64,{data_string}"
            }
        elif category in ["audio", "video"]:
            content_block = {
                "type": "media",
                "data": data_string,
                "mime_type": mime_type.split(";")[0].strip() if "codec=opus" in mime_type else mime_type
            }
            
        content = [
            {"type": "text", "text": f"User sent a {category}. Process this appropriately."},
            content_block,
        ]
        _logger.info(f"Media for Gemini processing - Category: {category}, MIME: {mime_type}")
        
    elif isinstance(user_input, dict) and user_input.get("context") is True:
        category = user_input["category"]
        data_string = base64.b64encode(user_input["data"]).decode("utf-8")
        mime_type = user_input["mime_type"]
        message_text = user_input.get("message", "")
        
        content_block = {
            "type": "media" if category in ["video", "audio"] else category,
            "data": data_string,
            "mime_type": mime_type,
        }
        
        # FIX: Include both text and media content
        content = [
            {"type": "text", "text": f"""The user's reply message is: {message_text}
            Generate a response that takes into account both the content of the {category} and the user's reply. 
            Respond naturally, as if continuing the conversation, without repeating the {category} description. 
            If the user's reply asks a question, answer it using the {category} context. 
            If it's just a reaction, respond in a relevant, concise way."""},
            content_block  # FIX: Actually include the media content
        ]
        
        _logger.info(f"Contextual reply processed - Category: {category}, Message: {message_text}")
        
    elif isinstance(user_input, str):
        content = user_input
    else:
        _logger.error(f"Invalid User Input: {user_input}")
        return {"content": "Sorry, I couldn't process your message.", "metadata": None}

    try:
        # FIX: Don't mutate DEFAULT_STATE, create a new input state
        input_state = {
            "messages": [{"role": "user", "content": content}]
        }
        
        # FIX: Initialize variables
        turn_count = 0
        
        for events in graph.stream(input_state, config=config):
            turn_count += 1
              
            for node_name, value in events.items():
                _logger.info(f"Processing node: {node_name}")
                    
                if node_name == "gemini" and "messages" in value and value["messages"]:
                    last_message = value["messages"][-1]
                    if hasattr(last_message, "content") and last_message.content:
                        final_response["content"] = last_message.content
                    if hasattr(last_message, "usage_metadata"):
                        final_response["metadata"] = last_message.usage_metadata
                            
                elif node_name == "tools":  # FIX: Correct indentation
                    _logger.info("Tools executed - ending conversation turn")
                    break
    
    except Exception as e:
        _logger.error(f"Graph streaming error: {e}")
        final_response = {"content": "I apologize, but I encountered an error processing your request.", "metadata": None}
    
    _logger.info(f"Final response after {turn_count} turns: {final_response}")
    return final_response

