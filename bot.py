from typing import Annotated, List
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import AnyMessage, add_messages
from langchain_core.messages import ToolMessage
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
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
import time 
import os
import threading

_logger = logger(__name__)

# Thread-safe globals
_checkpointer = None
_langgraph_conn = None
_langgraph_pid = None
_checkpointer_lock = threading.Lock()  # NEW: Thread safety


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
    """
    Get or create LangGraph checkpointer (process-safe and thread-safe with health checks)
    
    Returns:
        PostgresSaver: Thread-safe checkpointer instance
    """
    global _checkpointer, _langgraph_conn, _langgraph_pid
    
    # Fast path: connection exists and is healthy
    if _checkpointer is not None and _langgraph_conn is not None:
        current_pid = os.getpid()
        
        # Check if still same process
        if _langgraph_pid == current_pid and is_connection_alive(_langgraph_conn):
            return _checkpointer
    
    # Slow path: need to create or recreate connection
    with _checkpointer_lock:
        # Double-check pattern: another thread may have created it
        current_pid = os.getpid()
        
        if _checkpointer is not None and _langgraph_pid == current_pid and is_connection_alive(_langgraph_conn):
            return _checkpointer
        
        # Check 1: Different process (fork detected)
        if _langgraph_conn is not None and _langgraph_pid != current_pid:
            _logger.info(f"LangGraph: Fork detected (PID {_langgraph_pid} → {current_pid})")
            try:
                _langgraph_conn.close()
            except Exception as e:
                _logger.warning(f"Failed to close old connection: {e}")
            _langgraph_conn = None
            _checkpointer = None
        
        # Check 2: Connection exists but is dead/closed
        elif _langgraph_conn is not None and not is_connection_alive(_langgraph_conn):
            _logger.warning(f"LangGraph: Dead connection detected for PID {current_pid}, recreating...")
            try:
                _langgraph_conn.close()
            except Exception as e:
                _logger.warning(f"Failed to close dead connection: {e}")
            _langgraph_conn = None
            _checkpointer = None
        
        # Create new connection if needed
        if _checkpointer is None:
            _logger.info(f"Creating LangGraph checkpointer for PID {current_pid}")
            
            try:
                # Proper SSL and connection configuration
                conn_params = make_conninfo(
                    f"postgresql://{DB_URL}",
                    sslmode='require',
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
                
                # Test connection immediately
                _langgraph_conn.execute("SELECT 1").fetchone()
                _logger.info("LangGraph connection test successful")
                
                _checkpointer = PostgresSaver(_langgraph_conn)
                
                # Setup tables (idempotent)
                try:
                    _checkpointer.setup()
                    _logger.info("LangGraph DB setup successful")
                except Exception as e:
                    _logger.debug(f"LangGraph setup (tables may already exist): {e}")
                
                _langgraph_pid = current_pid
                _logger.info(f"✅ LangGraph checkpointer ready for PID {current_pid}")
                
            except Exception as e:
                _logger.error(f"Failed to create LangGraph checkpointer: {e}", exc_info=True)
                _langgraph_conn = None
                _checkpointer = None
                raise
        
        return _checkpointer


class State(TypedDict):
    """LangGraph state definition"""
    messages: Annotated[List[AnyMessage], add_messages]
    operator_active: bool


@tool("RespondWithMedia")
def RespondWithMedia(category: str, subcategory: str = "", *, config: RunnableConfig) -> dict:
    """
    Send WhatsApp media from the Joy Invite sample library.

    VALID ARGUMENTS (LLM MUST FOLLOW EXACTLY):

    CATEGORIES WITH SUBCATEGORIES  (MUST pass BOTH category and subcategory)
    ----------------------------------------------------------------------
    - category="south_india"   subcategory ∈ {"2d", "3d", "ai"}
    - category="north_india"   subcategory ∈ {"2d", "3d", "ai"}
    - category="punjabi"       subcategory ∈ {"2d", "3d"}
    - category="engagement"    subcategory ∈ {"2d", "3d"}

    CATEGORIES WITHOUT SUBCATEGORIES (MUST pass subcategory="")
    -----------------------------------------------------------
    - "save_the_date"
    - "welcome_board"
    - "anniversary"
    - "janoi"
    - "muslim"
    - "wardrobe"
    - "story"
    - "house_warming"
    - "baby_shower"
    - "mundan"
    - "birthday"
    - "utility"

    RULES:
    - Use ONLY the category and subcategory values listed above.
    - Always use lowercase and underscores, e.g. "south_india", "save_the_date".
    - Do NOT invent new categories or subcategories.
    - If user asks for a style that maps clearly to one of these, choose the closest valid category/subcategory.
    """
    user_ph = config.get("configurable", {}).get("thread_id")
    if not user_ph:
        _logger.error("RespondWithMedia called without thread_id")
        return {"status": "error", "message": "Missing user phone number"}

    # Normalization
    raw_category = category or ""
    raw_subcat = subcategory or ""
    norm_category = raw_category.strip().lower().replace(" ", "_").replace("-", "_")
    norm_subcat = raw_subcat.strip().lower()

    CATS_WITH_SUB = {
        "south_india": {"2d", "3d", "ai"},
        "north_india": {"2d", "3d", "ai"},
        "punjabi": {"2d", "3d"},
        "engagement": {"2d", "3d"},
    }

    CATS_NO_SUB = {
        "save_the_date",
        "welcome_board",
        "anniversary",
        "janoi",
        "muslim",
        "wardrobe",
        "story",
        "house_warming",
        "baby_shower",
        "mundan",
        "birthday",
        "utility",
    }

    # Validation
    if norm_category in CATS_WITH_SUB:
        if norm_subcat not in CATS_WITH_SUB[norm_category]:
            _logger.error(
                f"Invalid subcategory '{norm_subcat}' for category '{norm_category}'. "
                f"Valid: {sorted(CATS_WITH_SUB[norm_category])}"
            )
            return {
                "status": "error",
                "message": (
                    f"Invalid subcategory '{raw_subcat}' for '{raw_category}'. "
                    f"Valid options: {sorted(CATS_WITH_SUB[norm_category])}"
                ),
            }
    elif norm_category in CATS_NO_SUB:
        if norm_subcat:
            _logger.error(
                f"Category '{norm_category}' does not support subcategories; got '{norm_subcat}'"
            )
            return {
                "status": "error",
                "message": f"Category '{raw_category}' does not have subcategories.",
            }
    else:
        _logger.error(f"Unknown media category '{norm_category}' (raw='{raw_category}')")
        return {
            "status": "error",
            "message": f"Unknown media category '{raw_category}'.",
        }

    _logger.info(
        f"[MEDIA TOOL] Normalized call: category='{norm_category}', "
        f"subcategory='{norm_subcat}', user_ph={user_ph}"
    )

    try:
        tool_response = send_media_tool(
            category=norm_category,
            subcategory=norm_subcat,
            user_ph=user_ph,
        )
        return {"status": "success", "data": tool_response}
    except Exception as e:
        _logger.error(f"RespondWithMedia tool failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@tool("RequestIntervention")
def RequestIntervention(
    status: bool = True,
    *,
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command:
    """
    Tool for Gemini to request manual takeover when it cannot handle a user query.
    
    Args:
        status: Whether to request intervention (always True)
        config: Runtime configuration with thread_id
        state: Current conversation state
        tool_call_id: ID of this tool call
    
    Returns:
        Command: LangGraph command to update state
    """
    user_ph = config.get("configurable", {}).get("thread_id")
    
    if not user_ph:
        _logger.error("Missing thread_id in RequestIntervention tool call")
        return Command(
            update={
                "messages": [ToolMessage("Error: Missing user phone", tool_call_id=tool_call_id)]
            }
        )
    
    try:
        callIntervention(state, user_ph)
        _logger.info(f"Intervention requested for {user_ph}")
        
        return Command(
            update={
                "operator_active": True,
                "messages": [ToolMessage("Intervention requested successfully", tool_call_id=tool_call_id)]
            }
        )
    except Exception as e:
        _logger.error(f"RequestIntervention tool failed for {user_ph}: {e}", exc_info=True)
        return Command(
            update={
                "messages": [ToolMessage(f"Error requesting intervention: {str(e)}", tool_call_id=tool_call_id)]
            }
        )


# Load system prompt
try:
    with open("gemini_system_prompt.txt", "r", encoding="utf-8") as f1:
        GEMINI_SYSTEM_PROMPT = f1.read()
    _logger.info("Gemini system prompt loaded successfully")
except FileNotFoundError:
    _logger.error("gemini_system_prompt.txt not found!")
    GEMINI_SYSTEM_PROMPT = "You are a helpful assistant for Joy Invite, a digital invitation service."
except Exception as e:
    _logger.error(f"Failed to load system prompt: {e}")
    GEMINI_SYSTEM_PROMPT = "You are a helpful assistant for Joy Invite, a digital invitation service."


# Initialize Gemini model
try:
    gemini = init_chat_model("google_genai:gemini-2.5-flash")
    gemini_with_tools = gemini.bind_tools([RespondWithMedia, RequestIntervention])
    _logger.info("Gemini model initialized successfully")
except Exception as e:
    _logger.error(f"Failed to initialize Gemini model: {e}", exc_info=True)
    raise


# Create prompt template
prompt_template = ChatPromptTemplate.from_messages([
    ("system", "{system_message}"),
    MessagesPlaceholder("messages")
])

# Create agent chain
gemini_agent = prompt_template | gemini_with_tools


def gemini_node(state: State):
    """
    Main Gemini processing node
    
    Args:
        state: Current conversation state
        
    Returns:
        dict: Updated state with AI response
    """
    try:
        ai_resp = gemini_agent.invoke({
            "system_message": GEMINI_SYSTEM_PROMPT,
            "messages": state['messages']
        })
        _logger.info(f"Gemini raw response: {repr(ai_resp)}")  # <-- add this
        return {"messages": [ai_resp]}
    
    except Exception as e:
        _logger.error(f"Gemini node error: {e}", exc_info=True)
        # Return error message to user
        from langchain_core.messages import AIMessage
        error_msg = AIMessage(
            content="I apologize, but I'm experiencing technical difficulties. "
                   "Please try again in a moment."
        )
        return {"messages": [error_msg]}


def isToolCall(state: State) -> str:
    """
    Check if Gemini called any tools
    
    Args:
        state: Current conversation state
        
    Returns:
        str: "tool_call" if tools were called, "no_tool_call" otherwise
    """
    last_message = state['messages'][-1]
    
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        _logger.info(f"Tool calls detected: {[tc['name'] for tc in last_message.tool_calls]}")
        return "tool_call"
    else:
        return "no_tool_call"


# Build the graph
graph_builder = StateGraph(State)

# Add nodes
graph_builder.add_node("gemini", gemini_node)
graph_builder.add_node("tools", ToolNode([RespondWithMedia, RequestIntervention]))

# Add edges
graph_builder.add_edge(START, "gemini")

# Conditional routing from gemini
graph_builder.add_conditional_edges(
    "gemini",
    isToolCall,
    {
        "tool_call": "tools",
        "no_tool_call": END
    }
)

# After tools, go back to gemini (for tool results)
graph_builder.add_edge("tools", "gemini")

_logger.info("LangGraph graph built successfully")


def get_graph():
    """
    Get compiled graph with health-checked checkpointer
    
    Returns:
        CompiledGraph: Ready-to-use LangGraph with checkpointer
    """
    try:
        checkpointer = get_checkpointer()
        
        # Configure recursion limit to prevent infinite loops
        return graph_builder.compile(
            checkpointer=checkpointer,
            interrupt_before=[],  # No interrupts
            interrupt_after=[],   # No interrupts
        )
    except Exception as e:
        _logger.error(f"Failed to compile graph: {e}", exc_info=True)
        raise


def stream_graph_updates(user_ph: str, user_input: dict) -> dict:
    """
    Stream graph updates and return final AI response
    
    Args:
        user_ph: User's phone number (used as thread_id)
        user_input: Formatted user input dict
        
    Returns:
        dict: {"content": str, "metadata": dict} with AI response
    """
    final_response = {"content": "", "metadata": None}
    config = {"configurable": {"thread_id": user_ph}}
    
    timings = {}
    
    try:
        # Step 1: Format content
        t0 = time.time()
        content = content_formatter(user_input)
        t1 = time.time()
        timings['content_formatting'] = t1 - t0
        _logger.info(f"Content formatted in {timings['content_formatting']:.2f}s for {user_ph}")
        
        # Step 2: Get fresh graph with process-safe checkpointer
        graph = get_graph()
        
        input_state = {"messages": [{"role": "user", "content": content}]}
        turn_count = 0
        max_turns = 5  # Prevent infinite loops
        
        t2 = time.time()
        
        # Stream graph execution
        for events in graph.stream(input_state, config=config):
            turn_count += 1
            
            if turn_count > max_turns:
                _logger.error(f"Max turns ({max_turns}) exceeded for {user_ph}")
                final_response["content"] = (
                    "I apologize, but I'm having trouble processing your request. "
                    "Let me connect you with our team for assistance."
                )
                break
            
            for node_name, value in events.items():
                _logger.debug(f"Processing node: {node_name} (turn {turn_count})")
                
                if node_name == "gemini" and "messages" in value and value["messages"]:
                    last_message = value["messages"][-1]
                    
                    # Extract content
                    if hasattr(last_message, "content") and last_message.content:
                        final_response["content"] = last_message.content
                    
                    # Extract metadata
                    if hasattr(last_message, "usage_metadata"):
                        final_response["metadata"] = last_message.usage_metadata
                
                elif node_name == "tools":
                    _logger.info(f"Tools executed in turn {turn_count}")
                    # Continue to next turn for tool results
        
        t3 = time.time()
        timings['ai_processing'] = t3 - t2
        timings['total'] = t3 - t0
        
        _logger.info(
            f"AI processing complete for {user_ph}: "
            f"{timings['ai_processing']:.2f}s ({turn_count} turns), "
            f"Total: {timings['total']:.2f}s"
        )
        
        # Validate response
        if not final_response["content"]:
            _logger.warning(f"Empty AI response for {user_ph} after {turn_count} turns")
            final_response["content"] = (
                "I apologize, but I couldn't generate a proper response. "
                "Please try rephrasing your question."
            )
    
    except Exception as e:
        _logger.error(f"Graph streaming error for {user_ph}: {e}", exc_info=True)
        final_response = {
            "content": (
                "I apologize, but I encountered an error while processing your request. "
                "Our team has been notified. Please try again in a moment."
            ),
            "metadata": None
        }
    
    _logger.info(f"Final response for {user_ph} after {turn_count} turns: {len(final_response['content'])} chars")
    return final_response


# Module initialization
_logger.info("bot.py module loaded successfully")