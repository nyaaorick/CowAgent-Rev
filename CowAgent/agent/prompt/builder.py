"""
System Prompt Builder - 系统提示词构建器

实现模块化的系统提示词构建，支持工具、技能、记忆等多个子系统
"""

from __future__ import annotations
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from common.log import logger
from config import conf
from agent.prompt.manager import get_prompt


@dataclass
class ContextFile:
    """A context file (path + content)."""
    path: str
    content: str


class PromptBuilder:
    """System prompt builder."""
    
    def __init__(self, workspace_dir: str, language: str = "zh"):
        """
        初始化提示词构建器
        
        Args:
            workspace_dir: 工作空间目录
            language: 语言 ("zh" 或 "en")
        """
        self.workspace_dir = workspace_dir
        self.language = language
    
    def build(
        self,
        base_persona: Optional[str] = None,
        user_identity: Optional[Dict[str, str]] = None,
        tools: Optional[List[Any]] = None,
        context_files: Optional[List[ContextFile]] = None,
        skill_manager: Any = None,
        memory_manager: Any = None,
        runtime_info: Optional[Dict[str, Any]] = None,
        project_dir: Optional[str] = None,
        permission_mode: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        构建完整的系统提示词
        
        Args:
            base_persona: 基础人格描述（会被context_files中的AGENT.md覆盖）
            user_identity: 用户身份信息
            tools: 工具列表
            context_files: 上下文文件列表（AGENT.md, USER.md, RULE.md, BOOTSTRAP.md等）
            skill_manager: 技能管理器
            memory_manager: 记忆管理器
            runtime_info: 运行时信息
            **kwargs: 其他参数
            
        Returns:
            完整的系统提示词
        """
        return build_agent_system_prompt(
            workspace_dir=self.workspace_dir,
            language=self.language,
            base_persona=base_persona,
            user_identity=user_identity,
            tools=tools,
            context_files=context_files,
            skill_manager=skill_manager,
            memory_manager=memory_manager,
            runtime_info=runtime_info,
            project_dir=project_dir,
            permission_mode=permission_mode,
            **kwargs
        )


def build_agent_system_prompt(
    workspace_dir: str,
    language: str = "zh",
    base_persona: Optional[str] = None,
    user_identity: Optional[Dict[str, str]] = None,
    tools: Optional[List[Any]] = None,
    context_files: Optional[List[ContextFile]] = None,
    skill_manager: Any = None,
    memory_manager: Any = None,
    runtime_info: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None,
    permission_mode: Optional[str] = None,
    **kwargs
) -> str:
    """
    Build the agent system prompt.

    Section order (by importance and logical flow):
    1. Tooling - core capabilities, introduced first
    2. Skills - right after tools, since skills are read via the read tool
    3. Memory - memory recall and writing guidance
    3.5 Knowledge - structured knowledge base (injects knowledge/index.md)
    4. Workspace - working environment description
    4.5 Permissions - what this session may change (omitted for full access)
    5. User identity - user info (optional)
    6. Project context - AGENT.md, USER.md, RULE.md, MEMORY.md, BOOTSTRAP.md
    7. Runtime info - meta info (time, model, etc.)

    Args:
        workspace_dir: workspace directory
        language: language ("zh" or "en")
        base_persona: base persona description (deprecated, defined by AGENT.md)
        user_identity: user identity info
        tools: tool list
        context_files: context file list
        skill_manager: skill manager
        memory_manager: memory manager
        runtime_info: runtime info
        **kwargs: extra args

    Returns:
        The full system prompt.
    """
    sections = []

    # 1. Tooling (most important, goes first)
    if tools:
        sections.extend(_build_tooling_section(tools, language))

    # 2. Skills (right after tools, since they need the read tool)
    if skill_manager:
        sections.extend(_build_skills_section(skill_manager, tools, language))

    # 3. Memory (standalone memory capability)
    if memory_manager:
        sections.extend(
            _build_memory_section(memory_manager, tools, language, workspace_dir, project_dir)
        )

    # 3.5 Knowledge (structured knowledge base)
    if conf().get("knowledge", True):
        sections.extend(_build_knowledge_section(workspace_dir, language, project_dir))

    # 4. Workspace (working environment description). Two of its blocks only
    # hold when the context files were actually loaded, which sub agents skip.
    sections.extend(
        _build_workspace_section(
            workspace_dir, language, bool(context_files), project_dir=project_dir
        )
    )


    # 5. User identity (if present)
    if user_identity:
        sections.extend(_build_user_identity_section(user_identity, language))

    # 6. Project context files (AGENT.md, USER.md, RULE.md - define the persona)
    if context_files:
        sections.extend(_build_context_files_section(context_files, language))

    # 7. Runtime info (meta info, goes last)
    if runtime_info:
        sections.extend(_build_runtime_section(runtime_info, language))
        sections.extend(_build_team_section(runtime_info, language))

    # 8. Response language (always appended, independent of the skeleton language)
    sections.extend(_build_response_language_section(language))

    return "\n".join(sections)


def _build_response_language_section(language: str) -> List[str]:
    """Response-language rule, appended regardless of the prompt skeleton language.

    Keeps the agent's reply language aligned with the user's input by default,
    so a Chinese-built prompt still answers an English user in English, and Chinese
    input always gets natural Chinese replies without English greeting artifacts.
    """
    cfg = get_prompt("system_prompt.response_language", lang=language)
    if cfg and isinstance(cfg, dict) and "header" in cfg and "rules" in cfg:
        return [
            cfg["header"],
            "",
            *cfg["rules"],
            "",
        ]
    if language == "en":
        return [
            "## 🌐 Response language",
            "",
            "1. By default, strictly reply in the same language as the user's input (when the user writes in Chinese, always reply in fluent, natural Chinese), unless the user explicitly asks for another language.",
            "2. Never reply with generic English greeting templates (like 'Hello! If you have any questions...') when the user is communicating in Chinese.",
            "",
        ]
    return [
        "## 🌐 回复语言",
        "",
        "1. 严格使用与用户输入相同的语言回复（用户使用中文交流时，必须全程使用自然、贴合上下文的中文回复，除非用户明确要求使用其他语言）。",
        "2. 严禁在中文对话中回复通用的英文问候模板（如 'Hello! If you have any questions...' 等），必须结合用户的具体内容进行有温度、有帮助的回应。",
        "",
    ]



def _build_identity_section(base_persona: Optional[str], language: str) -> List[str]:
    """Base identity section - no longer needed, identity is defined by AGENT.md."""
    # Identity is fully defined by AGENT.md, so emit nothing here.
    return []


def _build_tooling_section(tools: List[Any], language: str) -> List[str]:
    """Build tooling section with concise tool list and call style guide."""
    is_en = language == "en"
    # One-line summaries for known tools (details are in the tool schema)
    if is_en:
        core_summaries = {
            "read": "read file content",
            "write": "create or overwrite a file",
            "edit": "make precise edits to a file",
            "ls": "list directory contents",
            "search_files": "search inside files by regex, or find files by name",
            "bash": "run shell commands",
            "terminal": "manage background processes",
            "web_search": "web search",
            "web_fetch": "fetch URL content",
            "memory_search": "search memory",
            "memory_get": "read memory content",
            "env_config": "manage API keys and skill config",
            "scheduler": "manage scheduled tasks and reminders",
            "send": "send a local file to the user (local files only; put URLs directly in the reply text)",
            "vision": "analyze images (recognition, description, OCR, etc.)",
            "subagent": "hand a self-contained task to a sub agent and get back only its conclusion",
        }
    else:
        core_summaries = {
            "read": "读取文件内容",
            "write": "创建或覆盖文件",
            "edit": "精确编辑文件",
            "ls": "列出目录内容",
            "search_files": "按正则搜索文件内容，或按文件名查找文件",
            "bash": "执行shell命令",
            "terminal": "管理后台进程",
            "web_search": "网络搜索",
            "web_fetch": "获取URL内容",
            "memory_search": "搜索记忆",
            "memory_get": "读取记忆内容",
            "env_config": "管理API密钥和技能配置",
            "scheduler": "管理定时任务和提醒",
            "send": "发送本地文件给用户（仅限本地文件，URL直接放在回复文本中）",
            "vision": "分析图片内容（识别、描述、OCR文字提取等）",
            "subagent": "把一件自成一体的任务交给子 Agent，只拿回它的结论",
        }

    # Preferred display order
    tool_order = [
        "read", "write", "edit", "ls", "search_files",
        "bash", "terminal",
        "web_search", "web_fetch",
        "memory_search", "memory_get",
        "env_config", "scheduler", "send", "vision", "subagent",
    ]

    # Build name -> summary mapping for available tools
    available = {}
    for tool in tools:
        name = tool.name if hasattr(tool, 'name') else str(tool)
        available[name] = core_summaries.get(name, "")

    # Generate tool lines: ordered tools first, then extras
    tool_lines = []
    for name in tool_order:
        if name in available:
            summary = available.pop(name)
            tool_lines.append(f"- {name}: {summary}" if summary else f"- {name}")
    for name in sorted(available):
        summary = available[name]
        tool_lines.append(f"- {name}: {summary}" if summary else f"- {name}")

    # The delegation rule earns its place in the prompt only when the tool is
    # there. Left to the tool description alone it competes with ~30 others and
    # loses: the model reaches for search directly and fills its own context.
    has_subagent = "subagent" in {
        tool.name if hasattr(tool, "name") else str(tool) for tool in tools
    }

    cfg = get_prompt("system_prompt.tooling", lang=language)
    if cfg and isinstance(cfg, dict):
        header = cfg.get("header", "## 🔧 Tooling" if is_en else "## 🔧 工具系统")
        available_prefix = cfg.get("available_prefix", "Available tools (names are case-sensitive, call exactly as listed):" if is_en else "可用工具（名称大小写敏感，严格按列表调用）:")
        style_prefix = cfg.get("style_prefix", "Tool-calling style:" if is_en else "工具调用风格：")
        guidelines = cfg.get("guidelines", [])
        subagent_guideline = cfg.get("subagent_guideline", "")
        lines = [
            header,
            "",
            available_prefix,
            "\n".join(tool_lines),
            "",
            style_prefix,
            "",
            *guidelines,
            "",
        ]
        if has_subagent and subagent_guideline:
            lines.insert(-1, subagent_guideline)
        return lines

    if is_en:
        lines = [
            "## 🔧 Tooling",
            "",
            "Available tools (names are case-sensitive, call exactly as listed):",
            "\n".join(tool_lines),
            "",
            "Tool-calling style:",
            "",
            "- For multi-step tasks, complex decisions or sensitive operations, briefly explain what you are doing and why, so the user follows key progress",
            "- Keep going until the task is done, then report the result to the user",
            "- Always redact secrets, tokens and other sensitive info in replies",
            "- Put URLs directly in the reply text; the system handles and renders them. Don't download and re-send them via the send tool",
            "- Only call tools when the user's message clearly requires external action or data. NEVER call tools (especially web_search) for greetings, conversational chit-chat, single punctuation marks (e.g. '?', '？', '!'), or inputs without a specific task. For casual or ambiguous inputs, reply directly with friendly conversational text.",
            "",
        ]
        if has_subagent:
            # One line, and only the part the tool description cannot do for
            # itself: get the model to consider delegating at all. When and how
            # belong in the description, which it reads once it looks.
            lines.insert(
                -1,
                "- Hand a self-contained task that needs research, search or information gathering to `subagent`: one task, or several at once via tasks running in parallel; it brings back the conclusion",
            )
    else:
        lines = [
            "## 🔧 工具系统",
            "",
            "可用工具（名称大小写敏感，严格按列表调用）:",
            "\n".join(tool_lines),
            "",
            "工具调用风格：",
            "",
            "- 多步骤任务、复杂决策、敏感操作时，应简要说明当前在做什么、为什么这样做，让用户了解关键进展",
            "- 持续推进直到任务完成，完成后向用户报告结果",
            "- 回复中涉及密钥、令牌等敏感信息必须脱敏",
            "- URL链接直接放在回复文本中即可，系统会自动处理和渲染。无需下载后使用send工具发送",
            "- 仅在用户消息明确需要外部操作或检索数据时才调用工具。对于日常问候、随意见聊、单纯的标点符号（如 '?'、'？'、'！'）或无明确任务意图的简短输入，严禁调用工具（尤其是 web_search），直接以自然语言友好回复即可。",
            "",
        ]
        if has_subagent:
            lines.insert(
                -1,
                "- 需要深入调研、搜索或信息采集的独立任务，交给 `subagent`：可以单个任务，也可以用 tasks 同时执行多个任务，`subagent` 负责把结论带回来",
            )

    return lines


def _build_skills_section(skill_manager: Any, tools: Optional[List[Any]], language: str) -> List[str]:
    """Build the skills section."""
    if not skill_manager:
        return []
    
    # Resolve the read tool name
    read_tool_name = "read"
    if tools:
        for tool in tools:
            tool_name = tool.name if hasattr(tool, 'name') else str(tool)
            if tool_name.lower() == "read":
                read_tool_name = tool_name
                break
    
    cfg = get_prompt("system_prompt.skills", lang=language, read_tool_name=read_tool_name)
    if cfg and isinstance(cfg, dict):
        lines = [
            cfg.get("header", "## 🧩 Skills (mandatory)" if language == "en" else "## 🧩 技能系统（mandatory）"),
            "",
            *cfg.get("instructions", []),
        ]
    elif language == "en":
        lines = [
            "## 🧩 Skills (mandatory)",
            "",
            "Before replying: scan the <description> of every skill in <available_skills> below.",
            "",
            f"- If a skill's description matches the user's need: use the `{read_tool_name}` tool to read the SKILL.md at its <location> path, then strictly follow the instructions in the file. "
            "Prefer using a skill when one matches.",
            "- If multiple skills apply, pick the best-matching one, then read and follow it.",
            "- If no skill clearly applies: do not read any SKILL.md, just use the general tools.",
            "",
            f"**Important**: skills are not tools and cannot be called directly. The only way to use a skill is to read its SKILL.md with `{read_tool_name}`, then act on the file's content. "
            "Never read multiple skills at once — only read one after selecting it.",
            "",
            "Available skills:"
        ]
    else:
        lines = [
            "## 🧩 技能系统（mandatory）",
            "",
            "在回复之前：扫描下方 <available_skills> 中每个技能的 <description>。",
            "",
            f"- 如果有技能的描述与用户需求匹配：使用 `{read_tool_name}` 工具读取其 <location> 路径的 SKILL.md 文件，然后严格遵循文件中的指令。"
            "当有匹配的技能时，应优先使用技能",
            "- 如果多个技能都适用则选择最匹配的一个，然后读取并遵循。",
            "- 如果没有技能明确适用：不要读取任何 SKILL.md，直接使用通用工具。",
            "",
            f"**重要**: 技能不是工具，不能直接调用。使用技能的唯一方式是用 `{read_tool_name}` 读取 SKILL.md 文件，然后按文件内容操作。"
            "永远不要一次性读取多个技能，只在选择后再读取。",
            "",
            "以下是可用技能："
        ]
    
    # Append the skills list (built by skill_manager)
    try:
        skills_prompt = skill_manager.build_skills_prompt()
        logger.debug(f"[PromptBuilder] Skills prompt length: {len(skills_prompt) if skills_prompt else 0}")
        if skills_prompt:
            lines.append(skills_prompt.strip())
            lines.append("")
        else:
            logger.warning("[PromptBuilder] No skills prompt generated - skills_prompt is empty")
    except Exception as e:
        logger.warning(f"Failed to build skills prompt: {e}")
        import traceback
        logger.debug(f"Skills prompt error traceback: {traceback.format_exc()}")
    
    return lines


def _state_path_prefix(workspace_dir: str, project_dir: Optional[str]) -> str:
    """Absolute prefix for state files (memory/knowledge) under ``workspace_dir``.

    In project mode the cwd is the project, so a bare ``MEMORY.md`` would resolve
    into the project. Memory and knowledge must stay in ``workspace_dir``, so we
    prefix them with its absolute path. Default mode returns "" (paths unchanged).
    """
    if not project_dir:
        return ""
    import os as _os
    if _os.path.realpath(_os.path.expanduser(project_dir)) == _os.path.realpath(
        _os.path.expanduser(workspace_dir)
    ):
        return ""
    return workspace_dir.rstrip("/") + "/"


def _build_memory_section(
    memory_manager: Any,
    tools: Optional[List[Any]],
    language: str,
    workspace_dir: str = "",
    project_dir: Optional[str] = None,
) -> List[str]:
    """Build the memory section.

    ``workspace_dir``/``project_dir`` let project-mode sessions keep memory paths
    anchored to ``workspace_dir`` (absolute) instead of the project cwd.
    """
    if not memory_manager:
        return []

    # In project mode, memory files must be addressed absolutely under ~/cow.
    p = _state_path_prefix(workspace_dir, project_dir)
    mem_md = f"{p}MEMORY.md"
    mem_dir = f"{p}memory"
    kb_dir = f"{p}knowledge"

    has_memory_tools = False
    if tools:
        tool_names = [tool.name if hasattr(tool, 'name') else str(tool) for tool in tools]
        has_memory_tools = any(name in ['memory_search', 'memory_get'] for name in tool_names)

    if not has_memory_tools:
        return []

    from datetime import datetime
    today_file = datetime.now().strftime("%Y-%m-%d") + ".md"

    cfg = get_prompt(
        "system_prompt.memory",
        lang=language,
        mem_md=mem_md,
        mem_dir=mem_dir,
        kb_dir=kb_dir,
        today_file=today_file,
    )
    if cfg and isinstance(cfg, dict):
        return [
            cfg.get("header", "## 🧠 Memory" if language == "en" else "## 🧠 记忆系统"),
            "",
            cfg.get("recall_header", "### Memory Recall (mandatory)" if language == "en" else "### Memory Recall（mandatory）"),
            "",
            cfg.get("recall_intro", ""),
            "",
            *cfg.get("recall_rules", []),
            "",
            cfg.get("files_header", "**Memory file structure**:"),
            *cfg.get("file_items", []),
            "",
            cfg.get("writing_header", "### Writing memory" if language == "en" else "### 写入记忆"),
            "",
            cfg.get("writing_intro", ""),
            "",
            *cfg.get("writing_triggers", []),
            "",
            cfg.get("storage_header", "**Storage rules**:" if language == "en" else "**存储规则**:"),
            *cfg.get("storage_rules", []),
            "",
            cfg.get("principle", ""),
            "",
        ]

    if language == "en":
        lines = [
            "## 🧠 Memory",
            "",
            "### Memory Recall (mandatory)",
            "",
            "When the user asks about past events, references an earlier decision, mentions relationships, preferences or to-dos, or when you are unsure about something, **you must search memory before answering**.",
            "No need to re-search if the info is already in MEMORY.md. Full content and daily memory must be retrieved via tools.",
            "",
            "1. Location unknown → `memory_search` (keyword / semantic search)",
            "2. Location known → `memory_get` to read the exact lines",
            "3. Search returns nothing → `memory_get` to read the last two days of memory",
            "",
        "**Memory file structure**:",
        f"- `{mem_md}`: long-term memory index (already auto-loaded into context: core info, preferences, decisions, etc.)",
        f"- `{mem_dir}/YYYY-MM-DD.md`: daily memory; today is `{mem_dir}/{today_file}`",
        f"- `{kb_dir}/`: structured knowledge base (see the knowledge system below)",
            "",
            "### Writing memory",
            "",
            "In the following cases, **proactively** write info to memory files (no need to tell the user):",
            "",
            "- The user asks you to remember something, or uses words like \"remember\", \"from now on\", \"always\", \"never\", \"prefer\"",
            "- The user shares important personal preferences, habits or decisions",
            "- The conversation produces an important conclusion, plan or agreement",
            "- A complex task is completed and the key steps and results are worth recording",
            "",
        "**Storage rules**:",
        f"- Long-term core info → `{mem_md}`",
        f"- Today's events/progress → `{mem_dir}/{today_file}`",
        f"- Structured knowledge → `{kb_dir}/` (see the knowledge system)",
            "- Append → `edit` tool with empty oldText",
            "- Modify → `edit` tool with oldText set to the text to replace",
            "- **Never write sensitive info** (API keys, tokens, etc.)",
            "",
            "**Principle**: use memory naturally, as if you simply knew it; don't bring it up unless asked.",
            "",
        ]
    else:
        lines = [
            "## 🧠 记忆系统",
            "",
            "### Memory Recall（mandatory）",
            "",
            "当用户询问过往事件、引用之前的决定、提到人物关系、偏好、待办、或你对某事不确定时，**必须先检索记忆再回答**。",
            "如果 MEMORY.md 中已有相关信息则无需重复检索。完整内容和每日记忆需要通过工具检索。",
            "",
            "1. 不确定位置 → `memory_search` 关键词/语义检索",
            "2. 已知位置 → `memory_get` 直接读取对应行",
            "3. search 无结果 → `memory_get` 读最近两天记忆",
            "",
            "**记忆文件结构**:",
            f"- `{mem_md}`: 长期记忆索引（已自动加载到上下文，核心信息、偏好、决策等）",
            f"- `{mem_dir}/YYYY-MM-DD.md`: 每日记忆，今天是 `{mem_dir}/{today_file}`",
            f"- `{kb_dir}/`: 结构化知识库（见下方知识系统）",
            "",
            "### 写入记忆",
            "",
            "遇到以下情况时，**主动**将信息写入记忆文件（无需告知用户）：",
            "",
            "- 用户要求记住某些信息，或使用了「记住」「以后」「总是」「不要」「偏好」等表达",
            "- 用户分享了重要的个人偏好、习惯、决策",
            "- 对话中产生了重要的结论、方案、约定",
            "- 完成了复杂任务，值得记录关键步骤和结果",
            "",
            "**存储规则**:",
            f"- 长期核心信息 → `{mem_md}`",
            f"- 当天事件/进展 → `{mem_dir}/{today_file}`",
            f"- 结构化知识 → `{kb_dir}/`（见知识系统）",
            "- 追加 → `edit` 工具，oldText 留空",
            "- 修改 → `edit` 工具，oldText 填写要替换的文本",
            "- **禁止写入敏感信息**（API密钥、令牌等）",
            "",
            "**使用原则**: 自然使用记忆，就像你本来就知道；不用刻意提起，除非用户问起。",
            "",
        ]

    return lines


def _build_knowledge_section(
    workspace_dir: str, language: str, project_dir: Optional[str] = None
) -> List[str]:
    """Build knowledge wiki section. Injects knowledge/index.md when present.

    In project mode ``project_dir`` anchors knowledge paths to ``workspace_dir``
    (absolute) so writes don't leak into the project cwd.
    """
    # Resolve through state_dir so an Agent on the shared base (no knowledge/ of
    # its own) still gets the shared index injected, not an empty local one.
    from common import state_dir
    knowledge_root = str(state_dir.knowledge_dir(base=workspace_dir))
    index_path = os.path.join(knowledge_root, "index.md")
    if not os.path.exists(index_path):
        return []

    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            index_content = f.read().strip()
    except Exception:
        return []

    # Anchor knowledge paths to ~/cow when a project cwd is active.
    kb = f"{_state_path_prefix(workspace_dir, project_dir)}knowledge"

    cfg = get_prompt(
        "system_prompt.knowledge",
        lang=language,
        kb=kb,
    )
    if cfg and isinstance(cfg, dict):
        lines = [
            cfg.get("header", "## 📚 Knowledge" if language == "en" else "## 📚 知识系统"),
            "",
            cfg.get("intro", ""),
            "",
            cfg.get("auto_write_header", "### Auto-write rules (mandatory)" if language == "en" else "### 自动写入规则（mandatory）"),
            "",
            cfg.get("auto_write_intro", ""),
            "",
            *cfg.get("auto_write_scenarios", []),
            "",
            cfg.get("sync_rule", ""),
            "",
            cfg.get("warning", ""),
            "",
        ]
        if index_content:
            lines.extend([
                cfg.get("current_index_header", "### Current knowledge index" if language == "en" else "### 当前知识索引"),
                "",
                index_content,
                "",
            ])
        lines.extend([
            cfg.get("query_guide", "**How to query**: use `read` to open a knowledge page, or `memory_search` (knowledge is in the vector index)." if language == "en" else "**查询方式**：用 `read` 读取知识页面，或用 `memory_search` 检索（知识已纳入向量索引）。"),
            "",
        ])
        return lines

    if language == "en":
        lines = [
            "## 📚 Knowledge",
            "",
            f"You have a continuously growing personal knowledge base `{kb}/` — your long-term structured knowledge store.",
            "",
            "### Auto-write rules (mandatory)",
            "",
            "In the following cases you **must** write to the knowledge base alongside your reply, **directly, without asking the user**:",
            "",
            f"1. **User shares an article / link / document** → after reading and understanding, write the key points to `{kb}/sources/<slug>.md` in the same turn",
            f"2. **An in-depth discussion produces a conclusion / plan** → organize it into `{kb}/analysis/<slug>.md`",
            f"3. **The conversation involves an important entity** (person / company / project) → create or update `{kb}/entities/<name>.md`",
            f"4. **A technical concept / methodology is discussed** → organize it into `{kb}/concepts/<topic>.md`",
            "",
            f"After writing any knowledge page, you **must update** `{kb}/index.md` with a new index line in sync.",
            "For detailed page format and conventions, read the SKILL.md of the `knowledge-wiki` skill.",
            "",
            "⚠️ Don't ask \"should I save this to the knowledge base?\" — if a case above matches, just write it. This is instinctive.",
            "",
        ]
    else:
        lines = [
            "## 📚 知识系统",
            "",
            f"你拥有一个持续积累的个人知识库 `{kb}/`，这是你的长期结构化知识存储。",
            "",
            "### 自动写入规则（mandatory）",
            "",
            "以下场景**必须**在回复的同时写入知识库，**直接写入，不要询问用户是否需要**：",
            "",
            f"1. **用户分享了文章/链接/文档** → 阅读理解后，在同一轮回复中将要点写入 `{kb}/sources/<slug>.md`",
            f"2. **深度讨论产生了结论/方案** → 整理为 `{kb}/analysis/<slug>.md`",
            f"3. **对话涉及重要实体**（人物/公司/项目）→ 创建或更新 `{kb}/entities/<name>.md`",
            f"4. **讨论了技术概念/方法论** → 整理为 `{kb}/concepts/<topic>.md`",
            "",
            f"每次写入知识页面后，**必须同步更新** `{kb}/index.md` 添加一行索引。",
            "详细的页面格式和操作规范，请读取技能 `knowledge-wiki` 的 SKILL.md。",
            "",
            "⚠️ 不要问「要不要存到知识库」——符合上述场景就直接写入，这是你的本能行为。",
            "",
        ]

    if index_content:
        lines.extend([
            ("### Current knowledge index" if language == "en" else "### 当前知识索引"),
            "",
            index_content,
            "",
        ])

    lines.extend([
        ("**How to query**: use `read` to open a knowledge page, or `memory_search` (knowledge is in the vector index)."
         if language == "en" else
         "**查询方式**：用 `read` 读取知识页面，或用 `memory_search` 检索（知识已纳入向量索引）。"),
        "",
    ])

    return lines


def _build_user_identity_section(user_identity: Dict[str, str], language: str) -> List[str]:
    """Build the user identity section."""
    if not user_identity:
        return []
    
    is_en = language == "en"
    lines = [
        ("## 👤 User identity" if is_en else "## 👤 用户身份"),
        "",
    ]

    if user_identity.get("name"):
        lines.append(f"**{'Name' if is_en else '用户姓名'}**: {user_identity['name']}")
    if user_identity.get("nickname"):
        lines.append(f"**{'Preferred name' if is_en else '称呼'}**: {user_identity['nickname']}")
    if user_identity.get("timezone"):
        lines.append(f"**{'Timezone' if is_en else '时区'}**: {user_identity['timezone']}")
    if user_identity.get("notes"):
        lines.append(f"**{'Notes' if is_en else '备注'}**: {user_identity['notes']}")

    lines.append("")

    return lines


def _build_docs_section(workspace_dir: str, language: str) -> List[str]:
    """Docs-path section - removed, no longer needed."""
    # No docs section is generated anymore.
    return []


def _build_workspace_section(
    workspace_dir: str, language: str, context_files_loaded: bool = True,
    project_dir: Optional[str] = None,
) -> List[str]:
    """Build the workspace section.

    ``context_files_loaded`` gates the two blocks that are only true for an
    Agent serving a user directly. A sub agent gets neither the context files
    nor a user to talk to, so telling it that AGENT.md is already loaded would
    both misinform it and talk it out of reading the workspace rules itself.

    ``project_dir`` switches the section to the dual-directory layout used when
    the user has pointed the session at a project: the *project* is the working
    directory (relative paths, artifacts) while the Agent's workspace stays the
    *system* directory (memory/skills), reached with absolute paths.
    """
    normalized_project = None
    if project_dir:
        import os as _os
        if _os.path.realpath(_os.path.expanduser(project_dir)) != _os.path.realpath(
            _os.path.expanduser(workspace_dir or "")
        ):
            normalized_project = project_dir

    if normalized_project:
        return _build_project_workspace_section(
            workspace_dir, normalized_project, language, context_files_loaded
        )

    cfg = get_prompt("system_prompt.workspace", lang=language, workspace_dir=workspace_dir)
    if cfg and isinstance(cfg, dict):
        lines = [
            cfg.get("header", "## 📂 Workspace" if language == "en" else "## 📂 工作空间"),
            "",
            cfg.get("working_dir", f"Your working directory is: `{workspace_dir}`"),
            "",
            cfg.get("rules_header", "**Path rules** (very important):"),
            "",
            *cfg.get("rules", []),
            "",
        ]
        if context_files_loaded:
            lines += [
                cfg.get("auto_loaded_header", "**Important - files already auto-loaded**:" if language == "en" else "**重要说明 - 文件已自动加载**:"),
                "",
                cfg.get("auto_loaded_desc", ""),
                "",
                *cfg.get("auto_loaded_items", []),
                "",
                cfg.get("communication_header", "**💬 Communication norms**:" if language == "en" else "**💬 交流规范**:"),
                "",
                *cfg.get("communication_norms", []),
                "",
            ]
        cloud_website_lines = _build_cloud_website_section(workspace_dir)
        if cloud_website_lines:
            lines.extend(cloud_website_lines)
        return lines

    if language == "en":
        lines = [
            "## 📂 Workspace",
            "",
            f"Your working directory is: `{workspace_dir}`",
            "",
            "**Path rules** (very important):",
            "",
            f"1. **Base directory for relative paths**: all relative paths are relative to `{workspace_dir}`",
            "   - ✅ Correct: use relative paths for files inside the workspace, e.g. `AGENT.md`",
            f"   - ❌ Wrong: using a relative path for files in other directories (if not inside `{workspace_dir}`)",
            "",
            "2. **Accessing other directories**: to reach directories outside the workspace (project code, system files), **you must use absolute paths**",
            "   - ✅ Correct: e.g. `~/chatgpt-on-wechat`, `/usr/local/`",
            "   - ❌ Wrong: assuming a relative path points to another directory",
            "",
            "3. **Path resolution examples**:",
            f"   - relative `memory/` → actual `{workspace_dir}/memory/`",
            "   - absolute `~/chatgpt-on-wechat/docs/` → actual `~/chatgpt-on-wechat/docs/`",
            "",
            "4. **When unsure**: run `bash pwd` to confirm the current directory, or `ls .` to see where you are",
            "",
        ]
        if context_files_loaded:
            lines += [
                "**Important - files already auto-loaded**:",
                "",
                "The following files are **already auto-loaded** into the system prompt at session start, so you **don't need to read them again with the read tool**:",
                "",
                "- ✅ `AGENT.md`: loaded - your persona and soul; follow it strictly. When your name, personality or style changes, proactively `edit` this file",
                "- ✅ `USER.md`: loaded - the user's identity info. When the user changes how they're addressed, their name, etc., `edit` this file",
                "- ✅ `RULE.md`: loaded - workspace guide and rules; follow them strictly",
                "- ✅ `MEMORY.md`: loaded - long-term memory index (and per-contact PROFILE.md / MEMORY.md if configured)",
                "",
                "**💬 Communication norms**:",
                "",
                "- No need to expose file names for memory operations; use natural language. Say \"I'll remember that\" rather than \"updated MEMORY.md\"",
                "- Tell the user about key decisions and steps during a task, so they know what you're doing and why",
                "- Be genuinely helpful rather than performatively polite; solve the problem as much as you can",
                "- Keep replies well-structured and focused. Use **bold**, lists and sections to make info clear at a glance",
                "- Use emoji to make expression lively 🎯, but don't overdo it",
                "",
            ]
    else:
        lines = [
            "## 📂 工作空间",
            "",
            f"你的工作目录是: `{workspace_dir}`",
            "",
            "**路径使用规则** (非常重要):",
            "",
            f"1. **相对路径的基准目录**: 所有相对路径都是相对于 `{workspace_dir}` 而言的",
            f"   - ✅ 正确: 访问工作空间内的文件用相对路径，如 `AGENT.md`",
            f"   - ❌ 错误: 用相对路径访问其他目录的文件 (如果它不在 `{workspace_dir}` 内)",
            "",
            "2. **访问其他目录**: 如果要访问工作空间之外的目录（如项目代码、系统文件），**必须使用绝对路径**",
            f"   - ✅ 正确: 例如 `~/chatgpt-on-wechat`、`/usr/local/`",
            f"   - ❌ 错误: 假设相对路径会指向其他目录",
            "",
            "3. **路径解析示例**:",
            f"   - 相对路径 `memory/` → 实际路径 `{workspace_dir}/memory/`",
            f"   - 绝对路径 `~/chatgpt-on-wechat/docs/` → 实际路径 `~/chatgpt-on-wechat/docs/`",
            "",
            "4. **不确定时**: 先用 `bash pwd` 确认当前目录，或用 `ls .` 查看当前位置",
            "",
        ]
        if context_files_loaded:
            lines += [
                "**重要说明 - 文件已自动加载**:",
                "",
                "以下文件在会话启动时**已经自动加载**到系统提示词中，你**无需再用 read 工具读取**：",
                "",
                "- ✅ `AGENT.md`: 已加载 - 你的人格和灵魂设定，请严格遵循。当你的名字、性格或交流风格发生变化时，主动用 `edit` 更新此文件",
                "- ✅ `USER.md`: 已加载 - 用户的身份信息。当用户修改称呼、姓名等身份信息时，用 `edit` 更新此文件",
                "- ✅ `RULE.md`: 已加载 - 工作空间使用指南和规则，请严格遵循",
                "- ✅ `MEMORY.md`: 已加载 - 长期记忆索引（若本会话配置了好友专属 PROFILE.md / MEMORY.md 亦已自动注入）",
                "",
                "**💬 交流规范**:",
                "",
                "- 记忆相关操作无需暴露文件名，用自然语言表达即可。例如说「我已记住」而非「已更新 MEMORY.md」",
                "- 任务执行过程中的关键决策和步骤应该告知用户，让用户了解你在做什么、为什么这么做",
                "- 做真正有帮助的助手，而不是表演式的客套，尽可能帮忙解决问题",
                "- 回复应结构清晰、重点突出。善用 **加粗**、列表、分段等格式让信息一目了然",
                "- 适当使用 emoji 让表达更生动自然 🎯，但不要过度堆砌",
                "",
            ]

    # Cloud deployment: inject websites directory info and access URL
    cloud_website_lines = _build_cloud_website_section(workspace_dir)
    if cloud_website_lines:
        lines.extend(cloud_website_lines)
    
    return lines


def _build_project_workspace_section(
    workspace_dir: str, project_dir: str, language: str, context_files_loaded: bool
) -> List[str]:
    """Workspace section for a session pointed at a project directory.

    Two directories are in play and the model must not confuse them:
    - Project directory (the current working dir): relative paths and work
      products (documents, code, generated files, etc.) live here.
    - System directory (``workspace_dir``, e.g. ``~/cow``): memory and skills
      live here and are reached with absolute paths, never relative ones.
    """
    cfg = get_prompt(
        "system_prompt.project_workspace",
        lang=language,
        project_dir=project_dir,
        workspace_dir=workspace_dir,
    )
    if cfg and isinstance(cfg, dict):
        lines = [
            cfg.get("header", "## 📂 Workspace" if language == "en" else "## 📂 工作空间"),
            "",
            cfg.get("intro", ""),
            "",
            cfg.get("project_dir_line", f"- **Project directory (current working dir)**: `{project_dir}`"),
            cfg.get("system_dir_line", f"- **System directory (memory & skills)**: `{workspace_dir}`"),
            "",
            cfg.get("rules_header", "**Path rules** (very important):"),
            "",
            *cfg.get("rules", []),
            "",
        ]
        if context_files_loaded and cfg.get("auto_loaded"):
            lines += [
                cfg.get("auto_loaded"),
                "",
            ]
        cloud_website_lines = _build_cloud_website_section(workspace_dir)
        if cloud_website_lines:
            lines.extend(cloud_website_lines)
        return lines

    if language == "en":
        lines = [
            "## 📂 Workspace",
            "",
            "The user has opened a **project directory**. You are working inside the current project directory.",
            "",
            f"- **Project directory (current working dir)**: `{project_dir}`",
            f"- **System directory (memory & skills)**: `{workspace_dir}`",
            "",
            "**Path rules** (very important):",
            "",
            f"1. **Relative paths are based on the project directory** `{project_dir}`. Put your work products here (documents, code, generated files, etc.).",
            f"   - ✅ relative `output/report.html` → `{project_dir}/output/report.html`",
            "",
            f"2. **Memory and skills stay in the system directory** `{workspace_dir}`. Never write them into the project. Memory tools handle this for you; if you ever touch these files directly, use **absolute paths** under the system directory.",
            f"   - ✅ absolute `{workspace_dir}/MEMORY.md`",
            f"   - ❌ relative `MEMORY.md` (that would land in the project, which is wrong)",
            "",
            "3. **Accessing any other directory**: use absolute paths.",
            "",
            "4. **When unsure**: run `bash pwd` to confirm you are in the project directory.",
            "",
        ]
    else:
        lines = [
            "## 📂 工作空间",
            "",
            "用户已打开一个**项目目录**，你正在当前项目目录中工作。",
            "",
            f"- **项目目录（当前工作目录）**: `{project_dir}`",
            f"- **系统目录（记忆与技能）**: `{workspace_dir}`",
            "",
            "**路径使用规则** (非常重要):",
            "",
            f"1. **相对路径基于项目目录** `{project_dir}`。你的工作产物（文档、代码、生成的文件等）都放在这里。",
            f"   - ✅ 相对路径 `output/report.html` → `{project_dir}/output/report.html`",
            "",
            f"2. **记忆和技能仍在系统目录** `{workspace_dir}`，不要写入项目目录。记忆操作由记忆工具自动完成；若确需直接访问这些文件，请使用系统目录下的**绝对路径**。",
            f"   - ✅ 绝对路径 `{workspace_dir}/MEMORY.md`",
            f"   - ❌ 相对路径 `MEMORY.md`（那会落到项目目录里，是错误的）",
            "",
            "3. **访问其他任意目录**：使用绝对路径。",
            "",
            "4. **不确定时**：用 `bash pwd` 确认当前处于项目目录。",
            "",
        ]

    if context_files_loaded:
        if language == "en":
            lines += [
                "**Files already auto-loaded** (no need to `read` again): `AGENT.md`, `USER.md`, `RULE.md`, `MEMORY.md` (from the system directory).",
                "",
            ]
        else:
            lines += [
                "**已自动加载的文件**（无需再次 `read`）：`AGENT.md`、`USER.md`、`RULE.md`、`MEMORY.md`（来自系统目录）。",
                "",
            ]

    cloud_website_lines = _build_cloud_website_section(workspace_dir)
    if cloud_website_lines:
        lines.extend(cloud_website_lines)
    return lines


def _build_cloud_website_section(workspace_dir: str) -> List[str]:
    """Build cloud website access prompt when cloud deployment is configured."""
    try:
        from common.cloud_client import build_website_prompt
        return build_website_prompt(workspace_dir)
    except Exception:
        return []


def _build_context_files_section(context_files: List[ContextFile], language: str) -> List[str]:
    """Build the project context files section."""
    if not context_files:
        return []
    
    # Check whether AGENT.md is present
    has_agent = any(
        f.path.lower().endswith('agent.md') or 'agent.md' in f.path.lower()
        for f in context_files
    )
    
    is_en = language == "en"
    cfg = get_prompt("system_prompt.context_files", lang=language)
    header = cfg.get("header") if isinstance(cfg, dict) else ("# 📋 Project context" if is_en else "# 📋 项目上下文")
    intro = cfg.get("intro") if isinstance(cfg, dict) else ("The following project context files have been loaded:" if is_en else "以下项目上下文文件已被加载：")
    lines = [
        header,
        "",
        intro,
        "",
    ]

    has_contact_profile = any(
        f.path.lower().endswith('profile.md')
        for f in context_files
    )
    has_contact_memory = any(
        'users/' in f.path.lower() and f.path.lower().endswith('memory.md')
        for f in context_files
    )

    if has_agent:
        if is_en:
            lines.append("**`AGENT.md` is your soul file** 🪞: strictly follow the persona, tone and settings it defines. Be your real self, avoid stiff, template-like replies.")
            lines.append("When the user reveals new expectations about your personality, style, responsibilities or capability boundaries, proactively `edit` AGENT.md to reflect that evolution.")
        else:
            lines.append("**`AGENT.md` 是你的灵魂文件** 🪞：严格遵循其中定义的人格、语气和设定，做真实的自己，避免僵硬、模板化的回复。")
            lines.append("当用户通过对话透露了对你性格、风格、职责、能力边界的新期望，你应该主动用 `edit` 更新 AGENT.md 以反映这些演变。")
        lines.append("")

    if has_contact_profile:
        if is_en:
            lines.append("**`PROFILE.md` is this contact's private profile & response policy**: strictly observe these custom instructions when chatting with this contact.")
        else:
            lines.append("**`PROFILE.md` 是当前好友的专属档案与特定回复策略**：在与该好友对话时优先遵循其中的定制要求。")
        lines.append("")

    if has_contact_memory:
        if is_en:
            lines.append("**`memory/users/.../MEMORY.md` is this contact's private memory notes**: strictly confidential to this conversation, never leak to other contacts.")
        else:
            lines.append("**`memory/users/.../MEMORY.md` 是当前好友的历史专属备忘**：仅供本会话参考，绝不跨好友泄露。")
        lines.append("")
    
    # Append the content of each file
    for file in context_files:
        lines.append(f"## {file.path}")
        lines.append("")
        lines.append(file.content)
        lines.append("")
    
    return lines


def _build_team_section(runtime_info: Dict[str, Any], language: str) -> List[str]:
    """Name the other Agents sharing this conversation, if any. Empty for one.

    Addressing someone by name is routing, not delegation: the named Agent is
    already the one reading this prompt, so handover is left for work nobody
    was asked for by name.

    States the Agent's own name, which nothing else in the prompt does. Without
    it a mention reads as a third party and the Agent declines to answer on
    that stranger's behalf.
    """
    teammates = runtime_info.get("teammates")
    getter = runtime_info.get("_get_teammates")
    if callable(getter):
        try:
            teammates = getter()
        except Exception as e:
            logger.warning(f"[PromptBuilder] Failed to resolve teammates: {e}")
    if not teammates:
        return []

    # One line each, with what they are for: a bare list of names is enough to
    # address someone but not to decide whether the work is theirs.
    roster = []
    for item in teammates:
        if not item.get("id"):
            continue
        line = f"{item.get('name') or item['id']}(@{item['id']})"
        if item.get("description"):
            line += f"：{item['description']}" if language != "en" else f" — {item['description']}"
        roster.append(line)
    if not roster:
        return []

    own_id = runtime_info.get("agent_id") or ""
    own_name = runtime_info.get("agent_name") or own_id
    whoami = f"{own_name}(@{own_id})" if own_id else own_name

    cfg = get_prompt("system_prompt.team", lang=language, whoami=whoami)
    if cfg and isinstance(cfg, dict):
        return [
            cfg.get("header", "## 👥 Team conversation" if language == "en" else "## 👥 团队会话"),
            "",
            cfg.get("whoami_intro", f"You are {whoami}. Also in this conversation:" if language == "en" else f"你是 {whoami}。同在这个会话里的还有："),
            "",
            *[f"- {line}" for line in roster],
            "",
            cfg.get("history_rule", ""),
            "",
            cfg.get("turn_rule", ""),
            "",
            cfg.get("delegate_rule", ""),
            "",
        ]

    if language == "en":
        return [
            "## 👥 Team conversation",
            "",
            f"You are {whoami}. Also in this conversation:",
            "",
            *[f"- {line}" for line in roster],
            "",
            "Everyone here reads the same history. A reply that starts with "
            "someone's name in brackets was written by them; an unmarked one "
            "is your own. Do not take a teammate's work, or their promises, "
            "for yours.",
            "",
            "This turn is yours to answer. Answer as yourself. When the user "
            "wants a teammate's own words, let them address that teammate.",
            "",
            "Use agent_delegate for work that belongs to a teammate, and say "
            "who you handed it to and what you asked for.",
            "",
        ]
    return [
        "## 👥 团队会话",
        "",
        f"你是 {whoami}。同在这个会话里的还有：",
        "",
        *[f"- {line}" for line in roster],
        "",
        "大家读到的是同一份记录。以方括号加名字开头的回复出自那位同事，"
        "没有标注的才是你自己说的。不要把同事做过的事、许下的承诺当成你的。",
        "",
        "这一轮由你来回答，以你自己的身份回答即可。用户想听某位同事亲口说，"
        "让他去点那位同事。",
        "",
        "该由某位同事做的事，用 agent_delegate 交出去，并说明交给了谁、交办了什么。",
        "",
    ]


def _build_runtime_section(runtime_info: Dict[str, Any], language: str) -> List[str]:
    """Build the runtime info section - supports dynamic time."""
    if not runtime_info:
        return []
    
    is_en = language == "en"
    cfg = get_prompt("system_prompt.runtime", lang=language)
    header = (cfg.get("header") if isinstance(cfg, dict) else None) or ("## ⚙️ Runtime info" if is_en else "## ⚙️ 运行时信息")
    time_label = (cfg.get("time_label") if isinstance(cfg, dict) else None) or ("Current time" if is_en else "当前时间")
    lines = [
        header,
        "",
    ]

    # Add current time if available
    # Support dynamic time via callable function
    if callable(runtime_info.get("_get_current_time")):
        try:
            time_info = runtime_info["_get_current_time"]()
            time_line = f"{time_label}: {time_info['time']} {time_info['weekday']} ({time_info['timezone']})"
            lines.append(time_line)
            lines.append("")
        except Exception as e:
            logger.warning(f"[PromptBuilder] Failed to get dynamic time: {e}")
    elif runtime_info.get("current_time"):
        # Fallback to static time for backward compatibility
        time_str = runtime_info["current_time"]
        weekday = runtime_info.get("weekday", "")
        timezone = runtime_info.get("timezone", "")

        time_line = f"{time_label}: {time_str}"
        if weekday:
            time_line += f" {weekday}"
        if timezone:
            time_line += f" ({timezone})"

        lines.append(time_line)
        lines.append("")

    # Add other runtime info
    model_label = "model" if is_en else "模型"
    workspace_label = "workspace" if is_en else "工作空间"
    channel_label = "channel" if is_en else "渠道"
    runtime_parts = []
    # Support dynamic model via callable, fallback to static value
    if callable(runtime_info.get("_get_model")):
        try:
            runtime_parts.append(f"{model_label}={runtime_info['_get_model']()}")
        except Exception:
            if runtime_info.get("model"):
                runtime_parts.append(f"{model_label}={runtime_info['model']}")
    elif runtime_info.get("model"):
        runtime_parts.append(f"{model_label}={runtime_info['model']}")
    if runtime_info.get("workspace"):
        runtime_parts.append(f"{workspace_label}={runtime_info['workspace']}")
    # Only add channel if it's not the default "web"
    if runtime_info.get("channel") and runtime_info.get("channel") != "web":
        runtime_parts.append(f"{channel_label}={runtime_info['channel']}")

    if runtime_parts:
        lines.append(("Runtime: " if is_en else "运行时: ") + " | ".join(runtime_parts))
        lines.append("")

    return lines
