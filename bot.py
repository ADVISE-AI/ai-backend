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

# class State(TypedDict):
#     messages: Annotated[List[AnyMessage], add_messages]
#     # current_model: str
#     human_intervention_requested: bool
#     waiting_for_human_response: bool
#     human_response: str
#     # New fields for media processing
#     media_processed: bool
#     media_summary: str  # Text summary of media interaction for GPT
#     original_media_content: dict  # Keep original for Gemini, but don't pass to GPT

class State(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    human_intervention_requested: bool
    waiting_for_human_response: bool
    human_response: str
    media_processed: bool
    original_media_content: dict
    conversation_turn: int
    last_media_hash: str  # Track processed media
    turn_timestamp: float   

@tool("RespondWithMedia")
def RespondWithMedia(media_file_type: str, caption: str = "", *,config: RunnableConfig) -> dict:
    """
    Send the user WhatsApp media based on file type.
    Args:
        media_file_type: Type of media file to send ('video', 'image', 'audio')
        caption: optional caption for the media

    Always use exact values: "video", "image", or "audio"
    """
    id_list = search_db_tool(str(media_file_type))
    user_ph = config.get("configurable", {}).get("thread_id")
    responses = []

    for id in id_list:
        try:
            time.sleep(1)
            response = send_media(str(media_file_type), str(user_ph), id)
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
 
                rows = {
                    "conversation_id": conversation_id,
                    "direction": "outbound",
                    "sender_type": "ai",
                    "external_id": response['messages'][0]['id'],
                    "has_text": True if len(caption)>0 else False,
                    "message_text": caption if len(caption)>0 else None,
                    "media_info": json.dumps({"id": str(id), "mime_type": "video/mp4", "description":"NO DESCRIPTION"}),
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

# @tool("RequestIntervention")
# def RequestIntervention(state: Annotated[dict, InjectedState], config: RunnableConfig)->Command:
#    """ Request Human Agent to intervene """
#     user_ph = config['configurable']['thread_id']
    
#     return Command(update={
#         'human_intervention_requested': True
#     })

prompt_template = ChatPromptTemplate.from_messages([
    ("system", "{system_message}"), 
    MessagesPlaceholder("messages")
])

# gpt_prompt_template = ChatPromptTemplate.from_messages([])

gemini =  init_chat_model("google_genai:gemini-2.5-flash")
# gpt = init_chat_model("openai:gpt-4o-mini")

# gemini_with_tools = gemini.bind_tools([RespondWithMedia, RequestIntervention])
gemini_with_tools = gemini.bind_tools([RespondWithMedia])
gemini_agent = prompt_template | gemini_with_tools
# gpt_agent = prompt_template | gpt 

# with open("gemini_system_prompt.txt", "r") as f1, open("gpt_sys_prompt.txt", "r") as f2:
#     GEMINI_SYSTEM_PROMPT = f1.read()
#     GPT_SYSTEM_PROMPT = f2.read()

with open("gemini_system_prompt.txt", "r") as f1:
    GEMINI_SYSTEM_PROMPT = f1.read()
    
# def intervention_request_check(state:State):
#     request = state.get('human_intervention_requested')
#     if request == True:
#         print("Admin Intervention Requested!")
#         return "requested"
#     else:
#         return "not_requested"


# def intervention_handler(state: State):
#     if not state['waiting_for_human_response']:
#         state['waiting_for_human_response'] = True
#         response = input("Admin message: ")

#         return {'human_response': response}


def get_media_hash(media_content):
    """Generate hash for media content to detect duplicates"""
    if not media_content:
        return None
    
    content_str = f"{media_content.get('mime_type', '')}{len(media_content.get('data', b''))}"
    return hashlib.md5(content_str.encode()).hexdigest()

def gemini_node(state: State):
    current_time = time.time()
    turn_count = state.get("conversation_turn", 0)
    last_timestamp = state.get("turn_timestamp", 0)
    
    # Limit conversation turns
    if turn_count >= 5:
        _logger.warning("Max conversation turns reached, ending")
        return {
            "messages": [{"role": "assistant", "content": "Let me know if you need anything else!"}],
            "conversation_turn": turn_count + 1,
            "turn_timestamp": current_time
        }

    media_content = None
    last_message = state["messages"][-1]
    
    if hasattr(last_message, "content") and isinstance(last_message.content, list):
        for content_part in last_message.content:
            if isinstance(content_part, dict) and content_part.get("type") in ["image", "media", "video"]:
                media_content = content_part
                break

    # Check for duplicate media processing
    media_hash = get_media_hash(media_content)
    last_media_hash = state.get("last_media_hash")
    
    if media_hash and media_hash == last_media_hash:
        _logger.info("Same media detected, providing different response")
        return {
            "messages": [{"role": "assistant", "content": "I understand you like that option. Would you like to proceed with it, or do you have any questions about the customization process?"}],
            "conversation_turn": turn_count + 1,
            "turn_timestamp": current_time,
            "last_media_hash": media_hash
        }

    # Truncate conversation history to prevent memory explosion
    recent_messages = state["messages"][-5:]  # Keep only last 5 messages
    
    system_prompt = GEMINI_SYSTEM_PROMPT
    if turn_count > 2:
        system_prompt += "\n\nIMPORTANT: Keep responses brief. The user has already seen your samples. Focus on next steps or closing the conversation."

    ai_resp = gemini_agent.invoke({
        "system_message": system_prompt,
        "messages": recent_messages,  # Use truncated history
    })

    return {
        "messages": [ai_resp],
        "media_processed": bool(media_content),
        "original_media_content": media_content,
        "conversation_turn": turn_count + 1,
        "turn_timestamp": current_time,
        "last_media_hash": media_hash
    }


# def sanitize_for_gpt(state: State):


#     sanitized_messages = []
#     for msg in state["messages"]:
#         if hasattr(msg, 'content'):
#             if isinstance(msg.content, list):
#                 # keep only text parts
#                 text_parts = [part['text'] for part in msg.content if isinstance(part, dict) and part.get('type') == 'text']
#                 if text_parts:
#                     sanitized_messages.append(type(msg)(content=' '.join(text_parts), role=msg.role))
#             else:
#                 sanitized_messages.append(msg)
#         else:
#             sanitized_messages.append(msg)

#     # Inject Gemini’s findings for GPT
#     if state.get("media_summary"):
#         sanitized_messages.insert(
#             0,
#             SystemMessage(content=f"Context: {state['media_summary']}")
#         )

#     return sanitized_messages


# def gpt_node(state: State):
#     # Get sanitized messages (no media content)
#     sanitized_messages = sanitize_for_gpt(state)
    
#     ai_resp = gpt_agent.invoke({
#         "system_message": GPT_SYSTEM_PROMPT,
#         "messages": sanitized_messages,  # Use sanitized messages
#         "current_model": "gpt-4o-mini",
#     })

#     return {
#         "messages": [ai_resp], 
#         "current_model": "gpt-4o-mini"
#     }

# def intervene_node(state:State):
#     if state['waiting_for_human_response']:
#         human_msg = state['human_response']
#         return {"messages": [human_msg], "waiting_for_human_response": False, "human_response": ""}

def isToolCall(state: State):
    """Check if Gemini called any tools"""
    last_message = state['messages'][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tool_call"
    else:
        return "no_tool_call"

# def after_tools(state: State):
#     """After tools execute, always go to GPT for final text response"""
#     return "gpt"


graph_builder = StateGraph(State)

# graph_builder.add_node("gemini", gemini_node)
# graph_builder.add_node("gpt", gpt_node)
# # graph_builder.add_node("intervene", intervene_node)
# # graph_builder.add_node("tools", ToolNode([RespondWithMedia, RequestIntervention]))
# graph_builder.add_node("tools", ToolNode([RespondWithMedia]))
# graph_builder.add_edge(START, "gemini")
# # graph_builder.add_conditional_edges(START, intervention_request_check, {"requested": "intervene", "not_requested": "gemini"})
# graph_builder.add_conditional_edges("gemini", isToolCall, {"tool_call": "tools", "no_tool_call": "gpt"})
# # graph_builder.add_conditional_edges("tools", intervention_request_check, {"requested": "intervene", "not_requested": "gpt"})
# # graph_builder.add_edge("intervene", END)
# graph_builder.add_edge("tools", "gpt")
# graph_builder.add_edge("gpt", END)


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
#from IPython.display import Image, display

#try:
#    display(Image(graph.get_graph().draw_mermaid_png()))
#except Exception:
#    pass


# DEFAULT_STATE = {
#         "messages": [{"role": "user", "content": None}],
#         "current_model": None,
#         "human_intervention_requested": False,
#         "waiting_for_human_response": False,
#         "human_response": None,
#         "media_processed": False,
#         "media_summary": "",
#         "original_media_content": None
#     }


DEFAULT_STATE = {
    "messages": [{"role": "user", "content": None}],
    "human_intervention_requested": False,
    "waiting_for_human_response": False,
    "human_response": None,
    "media_processed": False,
    "original_media_content": None,
}

def stream_graph_updates(user_ph: str, user_input) -> dict:
    
    final_response = {"content": "", "metadata": None}
    content = None
    config = {"configurable": {"thread_id": user_ph}}
    
    if isinstance(user_input, dict) and user_input.get("context") is False:
        category = user_input["category"]
        data_string = base64.b64encode(user_input["data"]).decode("utf-8")
        mime_type = user_input["mime_type"]
        
        content_block= None

        if category == "image":
            if not mime_type.startswith("image/"):
                _logger.warning(f"Iavalid image MIME type: {mime_type}, defaulting to image/jpeg")
                mime_type = "image/jpeg"
            content_block = {
                "type": "image_url", 
                "image_url": f"data:{mime_type};base64,{data_string}"
            }

        elif category in ["audio", "video"]:
            content_block = {
                
                "type": "media",
                "data": data_string,  # Use base64 string directly
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

        content = [
            {"type": "text", "text": f"""he user’s reply message is: {message_text}
            Generate a response that takes into account both the content of the video and the user’s reply. 
            Respond naturally, as if continuing the conversation, without repeating the video description. 
            If the user’s reply asks a question, answer it using the video context. 
            If it’s just a reaction, respond in a relevant, concise way."""
}
        ]
        
        _logger.info(f"Contextual reply processed - Category: {category}, Message: {message_text}")

    elif isinstance(user_input, str):
        content = user_input
    else:
        _logger.error(f"Invalid User Input: {user_input}")
        return {"content": "Sorry, I couldn't process your message.", "metadata": None}

    try:
        current_state = graph.get_state(config)
        
        if current_state and current_state.values:
            message_count = len(current_state.values.get("messages", []))
            turn_count = current_state.values.get("conversation_turn", 0)
            
            if message_count > 10 or turn_count > 5:
                _logger.info(f"Clearing conversation state for {user_ph} - Messages: {message_count}, Turns: {turn_count}")
                
                initial_state = {
                    "messages": [],
                    "human_intervention_requested": False,
                    "waiting_for_human_response": False,
                    "human_response": None,
                    "media_processed": False,
                    "original_media_content": None,
                    "conversation_turn": 0,
                    "last_media_hash": None,
                    "turn_timestamp": time.time()
                }
                
                graph.update_state(config, initial_state)
        
        input_state = {
            "messages": [{"role": "user", "content": content}]
        }
        
        turn_count = 0
        max_turns = 3
        
        for events in graph.stream(input_state, config=config):
            turn_count += 1
            
            if turn_count > max_turns:
                _logger.warning(f"Breaking loop after {max_turns} turns for user {user_ph}")
                break
                
            for node_name, value in events.items():
                _logger.info(f"Processing node: {node_name}")
                
                if node_name == "gemini" and "messages" in value and value["messages"]:
                    last_message = value["messages"][-1]
                    if hasattr(last_message, "content") and last_message.content:
                        final_response["content"] = last_message.content
                    if hasattr(last_message, "usage_metadata"):
                        final_response["metadata"] = last_message.usage_metadata
                        
                elif node_name == "tools":
                    _logger.info("Tools executed - ending conversation turn")
                    break
    except Exception as e:
        _logger.error(f"Graph streaming error: {e}")
        final_response = {"content": "I apologize, but I encountered an error processing your request.", "metadata": None}

    _logger.info(f"Final response after {turn_count} turns: {final_response}")
    return final_response
