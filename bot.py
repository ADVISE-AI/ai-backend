from typing import Annotated, List
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END 
from langgraph.graph.message import AnyMessage, add_messages
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode, InjectedState
from langchain_core.tools import tool
from langgraph.types import Command
from langgraph.checkpoint.postgres import PostgresSaver
from config import GOOGLE_API_KEY, DB_URL, logger

from agent_tools.media_response_tool import send_media_tool
from agent_tools.request_for_intervention import callIntervention
from utility.content_block import content_formatter

from psycopg import Connection

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
    operator_active: bool

@tool("RespondWithMedia")
def RespondWithMedia(media_description: str, * ,config: RunnableConfig) -> dict:
    """
    Send the user WhatsApp media based on file type.
    Args:
         media_description: Choose one of 'ai', '3d', '2d', 'info', 'customer_review', 'intro'.
    """
    user_ph = config.get("configurable", {}).get("thread_id")

    tool_response = send_media_tool(media_description=media_description, user_ph = user_ph)

    return tool_response
    

@tool("RequestIntervention")
def RequestIntervention(
    status: bool = True, *, config: RunnableConfig, state: Annotated[dict, InjectedState]
) -> Command:
    """
    Tool for Gemini to request manual takeover when it cannot handle a user query.
    """
    user_ph = config.get("configurable", {}).get("thread_id")
    callIntervention(state, user_ph)
    
    return Command(update={"operator_active": True})


prompt_template = ChatPromptTemplate.from_messages([
    ("system", "{system_message}"),
    MessagesPlaceholder("messages")
])


gemini =  init_chat_model("google_genai:gemini-2.5-flash")

gemini_with_tools = gemini.bind_tools([RespondWithMedia, RequestIntervention])
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
graph_builder.add_node("tools", ToolNode([RespondWithMedia, RequestIntervention]))
graph_builder.add_edge(START, "gemini")
graph_builder.add_conditional_edges("gemini", isToolCall, {
    "tool_call": "tools",
    "no_tool_call": END  
})
graph_builder.add_edge("tools", "gemini")
graph_builder.add_edge("gemini", END) 


graph = graph_builder.compile(checkpointer = checkpointer)

DEFAULT_STATE = {
    "messages": [{"role": "user", "content": None}],
}


def stream_graph_updates(user_ph: str, user_input: dict) -> dict:
    final_response = {"content": "", "metadata": None}
    content = None
    config = {"configurable": {"thread_id": user_ph}}
    
    content = content_formatter(user_input)
    try:
        input_state = {
            "messages": [{"role": "user", "content": content}]
        }
        

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
        final_response = {"content": "", "metadata": None}
    
    _logger.info(f"Final response after {turn_count} turns: {final_response}")
    return final_response

