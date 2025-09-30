from config import logger
import base64

_logger = logger(__name__)

def content_formatter(user_input: dict) -> str | list | dict:
    """
    Format user input into content blocks for AI processing
    
    Args:
        user_input: Dict containing message data with context and class info
        
    Returns:
        Formatted content for AI (string, list of content blocks, or error dict)
    """
    has_context = user_input.get("context", False)
    
    # Handle non-contextual messages (standalone)
    if has_context is False:
        return _format_non_contextual(user_input)
    
    # Handle contextual messages (replies)
    elif has_context is True:
        return _format_contextual(user_input)
    
    # Invalid input
    else:
        _logger.error(f"Invalid User Input: {user_input}")
        return {
            "content": "Sorry, I couldn't process your message.",
            "metadata": None
        }


def _format_non_contextual(user_input: dict) -> str | list:
    """Format standalone messages without context"""
    message_class = user_input.get("class")
    
    if message_class == "media":
        return _format_media_message(user_input)
    
    elif message_class == "text":
        return _format_text_message(user_input)
    
    else:
        _logger.warning(f"Unknown message class: {message_class}")
        return ""


def _format_contextual(user_input: dict) -> str | list:
    """Format contextual messages (replies to previous messages)"""
    context_type = user_input.get("context_type")
    
    if context_type == "media":
        return _format_media_context_reply(user_input)
    
    elif context_type == "text":
        return _format_text_context_reply(user_input)
    
    else:
        _logger.warning(f"Unknown context type: {context_type}")
        return ""


def _format_media_message(user_input: dict) -> list:
    """Format standalone media message"""
    category = user_input["category"]
    data_string = base64.b64encode(user_input["data"]).decode("utf-8")
    mime_type = user_input["mime_type"]
    message_text = user_input.get("message", "")
    
    # Build content block based on media type
    content_block = _build_media_content_block(category, data_string, mime_type)
    
    # Combine text instruction with media
    content = [
        {
            "type": "text",
            "text": f"User sent a {category} with the caption: {message_text}. Process this appropriately."
        },
        content_block,
    ]
    
    _logger.info(f"Media for AI processing - Category: {category}, MIME: {mime_type}")
    return content


def _format_text_message(user_input: dict) -> str:
    """Format standalone text message"""
    message_text = user_input.get("message", "")
    
    _logger.info(f"Text for AI processing - Message: {message_text}")
    return message_text


def _format_media_context_reply(user_input: dict) -> list:
    """Format reply to a media message"""
    category = user_input["category"]
    data_string = base64.b64encode(user_input["data"]).decode("utf-8")
    mime_type = user_input["mime_type"]
    message_text = user_input.get("message", "")
    
    # Build media content block
    content_block = {
        "type": "media" if category in ["video", "audio"] else category,
        "data": data_string,
        "mime_type": mime_type,
    }
    
    # Build contextual prompt
    prompt = f"""The user's reply message is: {message_text}
Generate a response that takes into account both the content of the {category} and the user's reply.
Respond naturally, as if continuing the conversation, without repeating the {category} description.
If the user's reply asks a question, answer it using the {category} context.
If it's just a reaction, respond in a relevant, concise way."""
    
    content = [
        {"type": "text", "text": prompt},
        content_block
    ]
    
    _logger.info(f"Media context reply processed - Category: {category}, Message: {message_text}")
    return content


def _format_text_context_reply(user_input: dict) -> str:
    """Format reply to a text message"""
    context_message = user_input.get("context_message", "")
    message_text = user_input.get("message", "")
    
    prompt = f"""The user's reply message is: {message_text}
The previous message in the conversation was: {context_message}
Generate a response that takes into account both the previous message and the user's reply.
Respond naturally, as if continuing the conversation, without repeating the previous message.
If the user's reply asks a question, answer it using the previous message context.
If it's just a reaction, respond in a relevant, concise way."""
    
    _logger.info(f"Text context reply processed - Message: {message_text}")
    return prompt


def _build_media_content_block(category: str, data_string: str, mime_type: str) -> dict:
    """
    Build appropriate content block for media type
    
    Args:
        category: Media category (image, audio, video)
        data_string: Base64 encoded media data
        mime_type: MIME type of the media
        
    Returns:
        Formatted content block dict
    """
    if category == "image":
        # Validate image MIME type
        if not mime_type.startswith("image/"):
            _logger.warning(f"Invalid image MIME type: {mime_type}, defaulting to image/jpeg")
            mime_type = "image/jpeg"
        
        return {
            "type": "image_url",
            "image_url": f"data:{mime_type};base64,{data_string}"
        }
    
    elif category in ["audio", "video"]:
        # Clean up MIME type (remove codec info if present)
        clean_mime_type = mime_type.split(";")[0].strip() if "codec=opus" in mime_type else mime_type
        
        return {
            "type": "media",
            "data": data_string,
            "mime_type": clean_mime_type
        }
    
    else:
        # Generic media block for other types
        return {
            "type": "media",
            "data": data_string,
            "mime_type": mime_type
        }

