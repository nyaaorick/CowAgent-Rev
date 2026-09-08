import importlib
import importlib.util
import threading
from pathlib import Path
from typing import Dict, Any, Type
from agent.tools.base_tool import BaseTool
from common.log import logger
from config import conf


class ToolManager:
    """
    Tool manager for managing safe chat tools.
    """
    _instances: Dict[str, "ToolManager"] = {}
    _instances_lock = threading.Lock()

    def __new__(cls):
        from common.state_dir import real_state_root

        key = real_state_root()
        instance = cls._instances.get(key)
        if instance is not None:
            return instance
        with cls._instances_lock:
            instance = cls._instances.get(key)
            if instance is None:
                instance = super(ToolManager, cls).__new__(cls)
                instance.workspace_root = key
                instance.tool_classes = {}  # Store tool classes instead of instances
                instance._initialized = False
                cls._instances[key] = instance
            return instance

    @classmethod
    def instances(cls) -> list:
        """Every ToolManager built so far, for process-wide operations."""
        with cls._instances_lock:
            return list(cls._instances.values())

    @classmethod
    def reset_instances(cls) -> None:
        """Drop every cached instance. For tests."""
        with cls._instances_lock:
            cls._instances.clear()

    def __init__(self):
        if not hasattr(self, 'tool_classes'):
            self.tool_classes = {}  # Dictionary to store tool classes
        if not hasattr(self, '_mcp_tool_instances'):
            self._mcp_tool_instances = {}

    def load_tools(self, tools_dir: str = "", config_dict=None):
        """
        Load tools from both directory and configuration.

        :param tools_dir: Directory to scan for tool modules
        """
        if tools_dir:
            self._load_tools_from_directory(tools_dir)
            self._configure_tools_from_config()
        else:
            self._load_tools_from_init()
            self._configure_tools_from_config(config_dict)

    def _load_tools_from_init(self) -> bool:
        """
        Load tool classes from tools.__init__.__all__

        :return: True if tools were loaded, False otherwise
        """
        try:
            # Try to import the tools package
            tools_package = importlib.import_module("agent.tools")

            # Check if __all__ is defined
            if hasattr(tools_package, "__all__"):
                tool_classes = tools_package.__all__

                # Import each tool class directly from the tools package
                for class_name in tool_classes:
                    try:
                        # Skip base classes
                        if class_name in ["BaseTool", "ToolManager"]:
                            continue

                        # Get the class directly from the tools package
                        if hasattr(tools_package, class_name):
                            cls = getattr(tools_package, class_name)

                            if (
                                    isinstance(cls, type)
                                    and issubclass(cls, BaseTool)
                                    and cls != BaseTool
                            ):
                                try:
                                    # Skip tools that need special initialization
                                    if class_name in ["MemorySearchTool", "MemoryGetTool"]:
                                        logger.debug(f"Skipped tool {class_name} (requires memory_manager)")
                                        continue
                                    # McpTool instances are registered dynamically via _load_mcp_tools()
                                    if class_name == "McpTool":
                                        logger.debug(f"Skipped tool {class_name} (registered dynamically via mcp_servers config)")
                                        continue
                                    
                                    # Create a temporary instance to get the name
                                    temp_instance = cls()
                                    tool_name = temp_instance.name
                                    # Store the class, not the instance
                                    self.tool_classes[tool_name] = cls
                                    logger.debug(f"Loaded tool: {tool_name} from class {class_name}")
                                except ImportError as e:
                                    # Handle missing dependencies with helpful messages
                                    error_msg = str(e)
                                    if "markdownify" in error_msg:
                                        logger.warning(
                                            f"[ToolManager] {cls.__name__} not loaded - missing markdownify.\n"
                                            f"  Install with: pip install markdownify"
                                        )
                                    else:
                                        logger.warning(f"[ToolManager] {cls.__name__} not loaded due to missing dependency: {error_msg}")
                                except Exception as e:
                                    logger.error(f"Error initializing tool class {cls.__name__}: {e}")
                    except Exception as e:
                        logger.error(f"Error importing class {class_name}: {e}")

                return len(self.tool_classes) > 0
            return False
        except ImportError:
            logger.warning("Could not import agent.tools package")
            return False
        except Exception as e:
            logger.error(f"Error loading tools from __init__.__all__: {e}")
            return False

    def _load_tools_from_directory(self, tools_dir: str):
        """Dynamically load tool classes from directory"""
        tools_path = Path(tools_dir)

        # Traverse all .py files
        for py_file in tools_path.rglob("*.py"):
            # Skip initialization files and base tool files
            if py_file.name in ["__init__.py", "base_tool.py", "tool_manager.py"]:
                continue

            # Get module name
            module_name = py_file.stem

            try:
                # Load module directly from file
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Find tool classes in the module
                    for attr_name in dir(module):
                        cls = getattr(module, attr_name)
                        if (
                                isinstance(cls, type)
                                and issubclass(cls, BaseTool)
                                and cls != BaseTool
                        ):
                            try:
                                # Skip memory tools (they need special initialization with memory_manager)
                                if attr_name in ["MemorySearchTool", "MemoryGetTool"]:
                                    logger.debug(f"Skipped tool {attr_name} (requires memory_manager)")
                                    continue
                                
                                # Create a temporary instance to get the name
                                temp_instance = cls()
                                tool_name = temp_instance.name
                                # Store the class, not the instance
                                self.tool_classes[tool_name] = cls
                            except ImportError as e:
                                # Handle missing dependencies with helpful messages
                                error_msg = str(e)
                                if "markdownify" in error_msg:
                                    logger.warning(
                                        f"[ToolManager] {cls.__name__} not loaded - missing markdownify.\n"
                                        f"  Install with: pip install markdownify"
                                    )
                                else:
                                    logger.warning(f"[ToolManager] {cls.__name__} not loaded due to missing dependency: {error_msg}")
                            except Exception as e:
                                logger.error(f"Error initializing tool class {cls.__name__}: {e}")
            except Exception as e:
                print(f"Error importing module {py_file}: {e}")

    def _configure_tools_from_config(self, config_dict=None):
        """Configure tool classes based on configuration file"""
        try:
            # Get tools configuration
            tools_config = config_dict or conf().get("tools", {})

            # Record tools that are configured but not loaded
            missing_tools = []

            # Store configurations for later use when instantiating
            self.tool_configs = tools_config

            # Check which configured tools are missing
            for tool_name in tools_config:
                if tool_name not in self.tool_classes:
                    missing_tools.append(tool_name)

            # If there are missing tools, record warnings
            if missing_tools:
                for tool_name in missing_tools:
                    if tool_name == "google_search":
                        logger.warning(
                            f"[ToolManager] Google Search tool is configured but may need API key.\n"
                            f"  Get API key from: https://serper.dev\n"
                            f"  Configure in config.json: tools.google_search.api_key"
                        )
                    else:
                        logger.warning(f"[ToolManager] Tool '{tool_name}' is configured but could not be loaded.")

        except Exception as e:
            logger.error(f"Error configuring tools from config: {e}")
    def sync_mcp_into_agent(self, agent) -> tuple:
        """Legacy no-op stub: MCP is completely disabled."""
        return ([], [])

    def create_tool(self, name: str) -> BaseTool:
        """
        Get a new instance of a tool by name.

        :param name: The name of the tool to get.
        :return: A new instance of the tool or None if not found.
        """
        tool_class = self.tool_classes.get(name)
        if tool_class:
            # Create a new instance
            tool_instance = tool_class()

            # Apply configuration if available
            if hasattr(self, 'tool_configs') and name in self.tool_configs:
                tool_instance.config = self.tool_configs[name]

            return tool_instance

        return None

    def list_tools(self) -> dict:
        """
        Get information about all loaded tools.

        :return: A dictionary with tool information.
        """
        result = {}
        for name, tool_class in self.tool_classes.items():
            # Create a temporary instance to get schema
            temp_instance = tool_class()
            result[name] = {
                "description": temp_instance.description,
                "parameters": temp_instance.get_json_schema()
            }

        return result

    def shutdown_mcp(self):
        """Legacy no-op stub."""
        pass
