"""System prompt and function schema composition for PipecatEngine nodes.

Extracts prompt and function composition logic from PipecatEngine into
reusable functions. Defines recording response mode markers and instructions.
"""

from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from api.services.workflow.pipecat_engine_custom_tools import CustomToolManager
    from api.services.workflow.workflow import Node, WorkflowGraph

from api.services.workflow.pipecat_engine_custom_tools import get_function_schema
from api.services.workflow.tools.knowledge_base import get_knowledge_base_tool

# ---------------------------------------------------------------------------
# Recording response mode markers
# ---------------------------------------------------------------------------

RECORDING_MARKER = "●"  # Play pre-recorded audio
TTS_MARKER = "▸"  # Generate dynamic TTS text

# ---------------------------------------------------------------------------
# Recording response mode system prompt instructions
# ---------------------------------------------------------------------------

RECORDING_RESPONSE_MODE_INSTRUCTIONS = """\
RESPONSE MODE INSTRUCTIONS - MANDATORY FORMAT:
Every response you generate MUST begin with a response mode indicator.
You have two modes for responding:

1. DYNAMIC SPEECH (▸): Generate text that will be converted to speech by TTS.
   Format: `▸` followed by a space and your full spoken response.
   Example: ▸ Hello! How can I help you today?

2. PRE-RECORDED AUDIO (●): Play a pre-recorded audio message.
   Format: `●` followed by a space followed by recording_id followed by provided transcript. Nothing else.
   Example: ● rec_greeting_01 [ Provided Transcript ]

RULES:
- Your response MUST start with either `▸` or `●` as the very first character.
- For `▸` (dynamic speech): Follow with a space and your full response text.
- For `●` (pre-recorded audio): Follow with a space and the recording_id and the provided transcript. No other text.
- Use `●` when a pre-recorded message matches the situation well.
- Use `▸` when you need to generate a dynamic, contextual response.
- NEVER mix modes in a single response. Choose one."""

# ---------------------------------------------------------------------------
# S2S conversational filler instructions
# ---------------------------------------------------------------------------

S2S_CONVERSATIONAL_FILLER_INSTRUCTIONS = """\
CONVERSATIONAL STYLE - NATURAL SPEECH PATTERNS:
You are having a natural voice conversation. Use conversational fillers and attributions to sound more human and engaging with long attribution.

APPROPRIATE FILLERS TO USE:
- "Hmmm..." or "Hmm..." when thinking or considering something
- "Acha..." or "Achha..." to show understanding or acknowledgment (Hindi/Urdu)
- "Ok..." or "Okay..." to acknowledge or confirm
- "Ohhh..." or "Oh..." when realizing or understanding something
- "I see..." when processing information
- "Right..." or "Got it..." to confirm understanding
- "Well..." when pausing before responding
- "So..." to transition between thoughts

USAGE GUIDELINES:
- Use these fillers naturally at the beginning or middle of responses
- Don't overuse them - sprinkle them naturally throughout the conversation
- Match the filler to the emotional context (e.g., "Ohhh!" for excitement, "Hmmm..." for thoughtfulness)
- Use culturally appropriate fillers based on the user's language (e.g., "Acha" for Hindi/Urdu speakers)
- Keep responses conversational and warm, not robotic"""


def compose_system_prompt_for_node(
    *,
    node: "Node",
    workflow: "WorkflowGraph",
    format_prompt: Callable[[str], str],
    has_recordings: bool,
    is_s2s: bool = False,
) -> str:
    """Compose the full system prompt text for a workflow node.

    Combines the global prompt, node-specific prompt, and (when recordings
    are enabled anywhere in the workflow) the recording response mode
    instructions into a single string.

    Args:
        node: The workflow node to compose the prompt for.
        workflow: The full workflow graph (needed for global node prompt).
        format_prompt: Callable to render template variables in prompts.
        has_recordings: Whether any node in the workflow uses recordings.
        is_s2s: Whether this is an S2S (Speech-to-Speech) pipeline.

    Returns:
        The composed system prompt text.
    """
    global_prompt = ""
    if workflow.global_node_id and node.add_global_prompt:
        global_node = workflow.nodes[workflow.global_node_id]
        global_prompt = format_prompt(global_node.prompt)

    formatted_node_prompt = format_prompt(node.prompt)

    parts = [p for p in (global_prompt, formatted_node_prompt) if p]

    if has_recordings and "RECORDING_ID:" in formatted_node_prompt:
        parts.append(RECORDING_RESPONSE_MODE_INSTRUCTIONS)

    if is_s2s:
        parts.append(S2S_CONVERSATIONAL_FILLER_INSTRUCTIONS)

    return "\n\n".join(parts)


async def compose_functions_for_node(
    *,
    node: "Node",
    builtin_function_schemas: list[dict],
    custom_tool_manager: Optional["CustomToolManager"],
) -> list[dict]:
    """Compose the function/tool schemas for a workflow node.

    Gathers built-in tools, knowledge-base tools, custom tools,
    and transition function schemas into a single list.

    Args:
        node: The workflow node to compose functions for.
        builtin_function_schemas: Pre-computed schemas for built-in tools.
        custom_tool_manager: Manager for user-defined custom tools (may be None).

    Returns:
        A list of function schemas to register with the LLM.
    """
    functions: list[dict] = []

    # Built-in tools (calculator, timezone)
    functions.extend(builtin_function_schemas)

    # Knowledge base retrieval tool
    if node.document_uuids:
        kb_tool_def = get_knowledge_base_tool(node.document_uuids)
        kb_schema = get_function_schema(
            kb_tool_def["function"]["name"],
            kb_tool_def["function"]["description"],
            properties=kb_tool_def["function"]["parameters"].get("properties", {}),
            required=kb_tool_def["function"]["parameters"].get("required", []),
        )
        functions.append(kb_schema)

    # Custom tools
    if node.tool_uuids and custom_tool_manager:
        custom_tool_schemas = await custom_tool_manager.get_tool_schemas(
            node.tool_uuids
        )
        functions.extend(custom_tool_schemas)

    # Transition function schemas
    for outgoing_edge in node.out_edges:
        function_schema = get_function_schema(
            outgoing_edge.get_function_name(), outgoing_edge.condition
        )
        functions.append(function_schema)

    return functions
