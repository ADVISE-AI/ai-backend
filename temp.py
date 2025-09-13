from typing import Annotated, List 
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END 
from langgraph.graph.message import AnyMessage, add_messages 
from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool 
from langgraph.types import Command
from langgraph.checkpoint.postgres import PostgresSaver
from config import OPENAI_API_KEY, GOOGLE_API_KEY, logger
from whatsapp import send_video
from utils import search_db_tool
from pydantic import BaseModel, Field
from db import pool
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
    current_agent: str


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
    responses = send_video(str(user_ph), id_list)

    return {"results": responses}

def create_handoff_tool(*, agent_name: str, description: str):
    name = f"transfer_to_{agent_name}"
    description = description + f" Transfer to {agent_name}."

    @tool(name)
    def handoff_tool() -> str:
        return f"Successfully transferred to {agent_name}"
    handoff_tool.__doc__ = description 
    return handoff_tool


def HumanMessageCheck(state: State):
    lastHumanMessage = None
    for msg in reversed(state['messages']):
        if isinstance(msg, HumanMessage):
            lastHumanMessage = msg
            break

    content = lastHumanMessage.content

    if isinstance(content, str):
        return "isText"
    elif isinstance(content, list):
        return "isNotText"
    



prompt_template = ChatPromptTemplate.from_messages([
    ("system", "{system_message}"), 
    MessagesPlaceholder("messages")
])

gemini =  init_chat_model("google_genai:gemini-2.5-flash")
gpt = init_chat_model("openai:gpt-4o-mini")

with open("gemini_system_prompt.txt") as f:
    GEMINI_SYSTEM_PROMPT = f.read()

with open("gpt_sys_prompt.txt") as f:
    GPT_SYSTEM_PROMPT = f.read()

handoff_to_gpt = create_handoff_tool(agent_name="gpt", description="Use this tool to transfer control to the GPT agent for crafting the final response.")
handoff_to_gemini = create_handoff_tool(agent_name="gemini", description="Use this tool to transfer control to the Gemini agent if media processing or media sending is required.")

gpt_bound = gpt.bind_tools([handoff_to_gemini])
gemini_bound = gemini.bind_tools([RespondWithMedia, handoff_to_gpt])

gpt_agent = prompt_template | gpt_bound
gemini_agent = prompt_template | gemini_bound

def router_func(state: State):
    route = HumanMessageCheck(state)
    if route == "isText":
        return {"current_agent": "gpt"}
    else:
        return {"current_agent": "gemini"}

def gpt_runner(state: State):
    ai_resp = gpt_agent.invoke({
        "system_message": GPT_SYSTEM_PROMPT, 
        "messages": state["messages"]
    })
    return {"messages": [ai_resp], "current_agent": "gpt"}

def gemini_runner(state: State):
    ai_resp = gemini_agent.invoke({
        "system_message": GEMINI_SYSTEM_PROMPT, 
        "messages": state["messages"] 
    })
    return {"messages": [ai_resp], "current_agent": "gemini"}

def tool_router(state: State):
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and len(last.tool_calls) > 0:
        return "use_tool"
    return "END"

def tool_condition(state: State):
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "type") and last_msg.type == "tool" and last_msg.name.startswith("transfer_to_"):
        agent = last_msg.name[len("transfer_to_"):]
        return agent
    else:
        return state["current_agent"]

graph_builder = StateGraph(State)
graph_builder.add_node("router", router_func)
graph_builder.add_node("gpt", gpt_runner)
graph_builder.add_node("gemini", gemini_runner)
graph_builder.add_node("tools", ToolNode([RespondWithMedia, handoff_to_gpt, handoff_to_gemini]))
graph_builder.add_edge(START, "router")
graph_builder.add_conditional_edges("router", lambda state: state["current_agent"], {"gpt": "gpt", "gemini": "gemini"})
graph_builder.add_conditional_edges("gpt", tool_router, {"use_tool": "tools", "END": END})
graph_builder.add_conditional_edges("gemini", tool_router, {"use_tool": "tools", "END": END})
graph_builder.add_conditional_edges("tools", tool_condition, {"gpt": "gpt", "gemini": "gemini"})
graph = graph_builder.compile(checkpointer = checkpointer)


def stream_graph_updates(user_ph: int, user_input) -> dict:
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
                "text": "Describe/Transcribe image/video/audio in great detail."
            },
            content_block
        ]
        _logger.info(f"Media category: {category}\n MIME type: {mime_type}\n Data String: {data_string}")
    elif type(user_input) is str:
        content = user_input
    
    else:
        _logger.fatal(f"Invalid User Input. \n ERROR LOG: user_input: {user_input} passed into the stream")


    for events in graph.stream(
        {"messages": [{"role": "user", "content": content}]}, 
        config={"configurable": {"thread_id": user_ph}}
    ):
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
    return final_response
        
