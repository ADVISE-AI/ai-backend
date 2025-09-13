from typing import Annotated, List 
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END 
from langgraph.graph.message import AnyMessage, add_messages
from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode, InjectedState
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres import PostgresSaver
from config import OPENAI_API_KEY, GOOGLE_API_KEY, logger
from whatsapp import send_video
from utils import search_db_tool
from pydantic import BaseModel, Field
from db import pool, engine, message
from sqlalchemy import insert
from datetime import datetime
import json
import base64
import requests

_logger = logger(__name__)

try:
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    _logger.info("Langgraph DB setup successfully")
except Exception as e:
    _logger.error("Langgraph DB setup Failed")
    _logger.info(f"Error Info: {str(e)}")

class State(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    current_model: str
    human_intervention_requested: bool
    waiting_for_human_response: bool
    human_response: str
    

class RespondWithMediaArgs(BaseModel):
    media_type: str = Field(
        ...,
        description="One of: 'wedding', 'anniversary', 'birthday'."
    )
    media_description: str = Field(
        ...,
        description=(
            "If media_type = 'wedding' → '2d sample' OR '3d sample with caricature'. "
            "If media_type = 'anniversary' or 'birthday' → '2d with caricature'."
        )
    )
    caption: str = Field(
        "",
        description="Optional caption for the video."
    )

@tool("RespondWithMedia", args_schema=RespondWithMediaArgs)
def RespondWithMedia(media_type: str, media_description: str, caption: str = "", *,config: RunnableConfig) -> dict:
    """
    Send the user WhatsApp videos.
    Args:
       
        media_type: 'wedding', 'anniversary', or 'birthday'.
        media_description: 
            - if media_type = 'wedding' → '2d sample' OR '3d sample with caricature'
            - if anniversary/birthday → '2d with caricature'
        user_ph: Not to be handled by the llm
        caption: optional caption for the video
    """
    id_list = search_db_tool(str(media_type), str(media_description))
    user_ph = config.get("configurable", {}).get("thread_id")
    responses = []
    for id in id_list:
        try:
            response = send_video(str(user_ph), id)
        except Exception as e:
            _logger.error(f"Failed to send media, media id: {id}")
            return {"response": str(e)}

        with engine.begin() as conn:
            try:
                rows = {
                    "direction": "outbound",
                    "sender_type": "AI",
                    "external_id": response['messages'][0]['id'],
                    "has_text": True if len(caption)>0 else False,
                    "message": caption if len(caption)>0 else None,
                    "media_info": json.dumps({"media_id": str(id), "mime_type": "video/mp4", "media_description":media_description}),
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

gpt_prompt_template = ChatPromptTemplate.from_messages([])

gemini =  init_chat_model("google_genai:gemini-2.5-flash")
gpt = init_chat_model("openai:gpt-4o-mini")

# gemini_with_tools = gemini.bind_tools([RespondWithMedia, RequestIntervention])
gemini_with_tools = gemini.bind_tools([RespondWithMedia])
gemini_agent = prompt_template | gemini_with_tools
gpt_agent = prompt_template | gpt 

with open("gemini_system_prompt.txt", "r") as f1, open("gpt_sys_prompt.txt", "r") as f2:
    GEMINI_SYSTEM_PROMPT = f1.read()
    GPT_SYSTEM_PROMPT = f2.read()


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
    
def gemini_node(state:State):
    ai_resp = gemini_agent.invoke({
        "system_message": GEMINI_SYSTEM_PROMPT,
        "messages": state["messages"],
        "current_model": state.get("current_model"),
        "human_intervention_requested": state.get("human_intervention_requested"),
        "waiting_for_human_response": state.get("waiting_for_human_response"),
    })

    return {
        "messages": [ai_resp],
        "current_model": "gemini-2.5-flash",
    }

def gpt_node(state:State):
    ai_resp = gpt_agent.invoke({
         "system_message": GPT_SYSTEM_PROMPT,
         "messages": state["messages"],
         "current_model": state["current_model"],
    })

    return {"messages": [ai_resp], "current_model": "gpt-4o-mini"}

# def intervene_node(state:State):
#     if state['waiting_for_human_response']:
#         human_msg = state['human_response']
#         return {"messages": [human_msg], "waiting_for_human_response": False, "human_response": ""}

def isToolCall(state:State):
    last_message = state['messages'][-1]
    if hasattr(last_message, "tool_calls"):
        return "tool_call"
    else:
        return "no_tool_call"

graph_builder = StateGraph(State)

graph_builder.add_node("gemini", gemini_node)
graph_builder.add_node("gpt", gpt_node)
# graph_builder.add_node("intervene", intervene_node)
# graph_builder.add_node("tools", ToolNode([RespondWithMedia, RequestIntervention]))
graph_builder.add_node("tools", ToolNode([RespondWithMedia]))
graph_builder.add_edge(START, "gemini")
# graph_builder.add_conditional_edges(START, intervention_request_check, {"requested": "intervene", "not_requested": "gemini"})
graph_builder.add_conditional_edges("gemini", isToolCall, {"tool_call": "tools", "no_tool_call": "gpt"})
# graph_builder.add_conditional_edges("tools", intervention_request_check, {"requested": "intervene", "not_requested": "gpt"})
# graph_builder.add_edge("intervene", END)
graph_builder.add_edge("tools", "gpt")
graph_builder.add_edge("gpt", END)


graph = graph_builder.compile(checkpointer = checkpointer)
#from IPython.display import Image, display

#try:
#    display(Image(graph.get_graph().draw_mermaid_png()))
#except Exception:
#    pass


DEFAULT_STATE = {"messages": [{"role": "user", "content": None}],
                 "current_model": None,
                 "human_intervention_requested": False,
                 "waiting_for_human_response": False,
                 "human_response": None}

def stream_graph_updates(user_ph: str, user_input) -> dict:
     final_response = {"content": "", "metadata": None}

     content = None

     if type(user_input) is dict:
        
         category = user_input["category"]
         data_string = base64.b64encode(user_input['data']).decode("utf-8")
         mime_type = user_input["mime_type"]
         content_block = {
             "type": category,
             "source_type": "base64",
             "data": data_string,
             "mime_type": mime_type,
         }

         content = [
             {
                 "type": "text", 
                 "text": "Process the media content and reply to the user accordingly"
             },
            content_block
         ]
         _logger.info(f"Media category: {category}\n MIME type: {mime_type}\n Data String: {data_string}")
     elif type(user_input) is str:
         content = user_input
    
     else:
         _logger.fatal(f"Invalid User Input. \n ERROR LOG: user_input: {user_input} passed into the stream")


     DEFAULT_STATE["messages"][0]["content"] = content

     for events in graph.stream(DEFAULT_STATE, config={"configurable": {"thread_id": user_ph}}):
         for node_name, value in events.items():
             print(f"=== EXECUTING NODE: {node_name} ===")
            
             if "messages" in value and value["messages"]:
                 last_message = value["messages"][-1]
                 _logger.info(f"Message type: {type(last_message).__name__}")
                 if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                     _logger.info(f"TOOL CALLS DETECTED: {len(last_message.tool_calls)} calls")
                     for i, tool_call in enumerate(last_message.tool_calls):
                         _logger.info(f"  Tool {i+1}: {tool_call}")
                
                 if hasattr(last_message, "type") and last_message.type == "tool":
                     _logger.info(f"TOOL EXECUTION RESULT: {last_message.content}")
                
                 if hasattr(last_message, "content") and last_message.content:
                     final_response["content"] = last_message.content
                 if hasattr(last_message, "usage_metadata"):
                     final_response["metadata"] = last_message.usage_metadata
    
     print("=== STREAM COMPLETED ===")
     _logger.info(final_response)
     return final_response
