# Import base tool
from agent.tools.base_tool import BaseTool
from agent.tools.tool_manager import ToolManager

# Import chat and media tools
from agent.tools.send.send import Send

# Import memory tools
from agent.tools.memory.memory_search import MemorySearchTool
from agent.tools.memory.memory_get import MemoryGetTool

# Import tools with optional dependencies
def _import_optional_tools():
    """Import tools that have optional dependencies"""
    from common.log import logger
    tools = {}

    # WebSearch Tool (conditionally loaded based on API key availability at init time)
    try:
        from agent.tools.web_search.web_search import WebSearch
        tools['WebSearch'] = WebSearch
    except ImportError as e:
        logger.error(f"[Tools] WebSearch not loaded - missing dependency: {e}")
    except Exception as e:
        logger.error(f"[Tools] WebSearch failed to load: {e}")

    # WebFetch Tool
    try:
        from agent.tools.web_fetch.web_fetch import WebFetch
        tools['WebFetch'] = WebFetch
    except ImportError as e:
        logger.error(f"[Tools] WebFetch not loaded - missing dependency: {e}")
    except Exception as e:
        logger.error(f"[Tools] WebFetch failed to load: {e}")

    # Vision Tool (conditionally loaded based on API key availability)
    try:
        from agent.tools.vision.vision import Vision
        tools['Vision'] = Vision
    except ImportError as e:
        logger.error(f"[Tools] Vision not loaded - missing dependency: {e}")
    except Exception as e:
        logger.error(f"[Tools] Vision failed to load: {e}")

    return tools

# Load optional tools
_optional_tools = _import_optional_tools()
WebSearch = _optional_tools.get('WebSearch')
WebFetch = _optional_tools.get('WebFetch')
Vision = _optional_tools.get('Vision')

# Export all safe tools
__all__ = [
    'BaseTool',
    'ToolManager',
    'Send',
    'MemorySearchTool',
    'MemoryGetTool',
    'WebSearch',
    'WebFetch',
    'Vision',
]

"""
Tools module for Agent.
"""
