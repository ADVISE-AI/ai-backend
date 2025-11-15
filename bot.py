from typing import Annotated, List
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END 
from langgraph.graph.message import AnyMessage, add_messages
from langchain_core.messages import ToolMessage
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode, InjectedState
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langgraph.checkpoint.postgres import PostgresSaver
from config import GOOGLE_API_KEY, DB_URL, logger

from agent_tools.media_response_tool import send_media_tool
from agent_tools.request_for_intervention import callIntervention
from utility.content_block import content_formatter

from psycopg import Connection
from psycopg.conninfo import make_conninfo

import os
_logger = logger(__name__)

_checkpointer = None
_langgraph_conn = None
_langgraph_pid = None

def is_connection_alive(conn):
    """Check if PostgreSQL connection is still alive"""
    if conn is None:
        return False
    try:
        # Quick health check
        conn.execute("SELECT 1").fetchone()
        return True
    except Exception as e:
        _logger.warning(f"Connection health check failed: {e}")
        return False

def get_checkpointer():
    """Get or create LangGraph checkpointer (process-safe with health checks)"""
    global _checkpointer, _langgraph_conn, _langgraph_pid
    
    current_pid = os.getpid()
    
    # Check 1: Different process (fork detected)
    if _langgraph_conn is not None and _langgraph_pid != current_pid:
        _logger.info(f"LangGraph: Fork detected (PID {_langgraph_pid} → {current_pid})")
        try:
            _langgraph_conn.close()
        except:
            pass
        _langgraph_conn = None
        _checkpointer = None

    elif _langgraph_conn is not None and not is_connection_alive(_langgraph_conn):
        _logger.warning(f"LangGraph: Dead connection detected for PID {current_pid}, recreating...")
        try:
            _langgraph_conn.close()
        except:
            pass
        _langgraph_conn = None
        _checkpointer = None
    
    if _checkpointer is None:
        _logger.info(f"Creating LangGraph checkpointer for PID {current_pid}")
        
        conn_params = make_conninfo(
            f"postgresql://{DB_URL}",
            # sslmode='require',
            connect_timeout=10,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
            tcp_user_timeout=30000,  # 30 seconds
        )
        
        _langgraph_conn = Connection.connect(
            conn_params,
            autocommit=True,
            prepare_threshold=0,
        )
        
        try:
            _langgraph_conn.execute("SELECT 1").fetchone()
            _logger.info("LangGraph connection test successful")
        except Exception as e:
            _logger.error(f"LangGraph connection test failed: {e}")
            _langgraph_conn = None
            raise
        
        _checkpointer = PostgresSaver(_langgraph_conn)
        
        try:
            _checkpointer.setup()
            _logger.info("LangGraph DB setup successful")
        except Exception as e:
            _logger.debug(f"LangGraph setup (tables may already exist): {e}")
        
        _langgraph_pid = current_pid
        _logger.info(f"✅ LangGraph checkpointer ready for PID {current_pid}")
    
    return _checkpointer

class State(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    operator_active: bool

@tool("RespondWithMedia")
def RespondWithMedia(category: str, subcategory: str = "", *, config: RunnableConfig) -> dict:
    """
    These are the supported categories. Only SOME categories have subcategories. 
LLM MUST follow this mapping EXACTLY:

------------------------------------------------------------
CATEGORIES WITH SUBCATEGORIES  (LLM MUST pass both arguments)
------------------------------------------------------------

1. south india
    valid subcategories: 2d, 3d, ai

2. north india
    valid subcategories: 2d, 3d, ai

3. punjabi
    valid subcategories: 2d, 3d

4. engagement
    valid subcategories: 2d, 3d


------------------------------------------------------------
CATEGORIES WITHOUT SUBCATEGORIES 
(LLM MUST pass subcategory=""; do NOT invent subcategories)
------------------------------------------------------------

- save the date  
- welcome board  
- wedding anniversary  
- janoi  
- muslim  
- wardrobe  
- story  
- house warming  
- baby shower  
- mundan  
- birthday  


------------------------------------------------------------
RULE SUMMARY (LLM MUST FOLLOW):
------------------------------------------------------------

1. If category supports subcategories → ALWAYS pass:
       category="<name>", subcategory="<2d|3d|ai>"

2. If category does NOT support subcategories → ALWAYS pass:
       category="<name>", subcategory=""

3. Use ALL LOWERCASE.  
   Only ONE WORD per argument (spaces must be removed or replaced with hyphens/underscores if needed).

4. Do NOT guess or invent new categories or subcategories.

5. Only use categories and subcategories EXACTLY as listed above.
    """
    _logger.info(f"[MEDIA TOOL] Called with category='{category}', subcategory='{subcategory}', user_ph={user_ph}")
    user_ph = config.get("configurable", {}).get("thread_id")
    tool_response = send_media_tool(category=category, subcategory=subcategory, user_ph=user_ph)
    return tool_response

    

@tool("RequestIntervention")
def RequestIntervention(
    status: bool = True, *, config: RunnableConfig, state: Annotated[dict, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command:
    """
    Tool for Gemini to request manual takeover when it cannot handle a user query.
    """
    user_ph = config.get("configurable", {}).get("thread_id")
    callIntervention(state, user_ph)


    return Command(update={"operator_active": True, "messages": [ToolMessage("Success", tool_call_id=tool_call_id)]})


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
        "messages": state['messages']
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


def get_graph():
    """Get compiled graph with health-checked checkpointer"""
    checkpointer = get_checkpointer()
    return graph_builder.compile(checkpointer=checkpointer)

DEFAULT_STATE = {
    "messages": [{"role": "user", "content": None}],
}


def stream_graph_updates(user_ph: str, user_input: dict) -> dict:
    final_response = {"content": "", "metadata": None}
    config = {"configurable": {"thread_id": user_ph}}
    
    import time
    timings = {}
    
    t0 = time.time()
    content = content_formatter(user_input)
    t1 = time.time()
    timings['content_formatting'] = t1 - t0
    _logger.info(f"Content formatted in {timings['content_formatting']:.2f} seconds")
    
    try:
        # Get fresh graph with process-safe checkpointer
        graph = get_graph()
        
        input_state = {"messages": [{"role": "user", "content": content}]}
        turn_count = 0
        
        t2 = time.time()
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
                
                elif node_name == "tools":
                    _logger.info("Tools executed - ending conversation turn")
                    break
        
        t3 = time.time()
        timings['ai_processing'] = t3 - t2
        _logger.info(f"AI processed in {timings['ai_processing']:.2f} seconds")
        _logger.info(f"Timings: {timings}")
        
    except Exception as e:
        _logger.error(f"Graph streaming error: {e}", exc_info=True)
        final_response = {"content": "", "metadata": None}
    
    _logger.info(f"Final response after {turn_count} turns: {final_response}")
    return final_response