"""Post-call summarization reusing the agent's configured LLM.

Works for both traditional (STT+LLM+TTS) and S2S (Gemini Live) pipelines
because it summarizes the stored transcript text, not live frames.
"""

import random

from loguru import logger

from api.services.pipecat.service_factory import create_llm_service_from_provider
from api.services.workflow.qa.llm_config import resolve_user_llm_config
from pipecat.processors.aggregators.llm_context import LLMContext

CALL_SUMMARY_SYSTEM_PROMPT = (
    "You are summarizing a phone call handled by a voice AI agent. "
    "Produce a concise summary (3-5 sentences) covering: the caller's intent, "
    "key information exchanged, and the outcome or next steps. "
    "Be factual and omit filler. If the transcript is empty or has no "
    "meaningful conversation, reply with exactly: No meaningful conversation."
)

# Keep prompts bounded for cost/latency; transcripts can be long.
MAX_TRANSCRIPT_CHARS = 12000
MIN_TRANSCRIPT_CHARS = 20


def _truncate(transcript: str) -> str:
    text = (transcript or "").strip()
    if len(text) > MAX_TRANSCRIPT_CHARS:
        return text[:MAX_TRANSCRIPT_CHARS] + "\n...[truncated]"
    return text


async def generate_call_summary(workflow_run, transcript_text: str) -> str | None:
    """Generate a call summary using the workflow owner's configured LLM.

    Returns the summary string, or None if generation should be skipped/failed.
    Never raises — callers treat None as "no summary".
    """
    text = _truncate(transcript_text)
    if len(text) < MIN_TRANSCRIPT_CHARS:
        logger.info(
            f"[run {workflow_run.id}] Skipping summary: transcript too short "
            f"({len(text)} chars)"
        )
        return None

    try:
        provider, model, api_key, kwargs = await resolve_user_llm_config(workflow_run)
    except Exception as e:
        logger.warning(f"[run {workflow_run.id}] Failed to resolve LLM config: {e}")
        return None

    # resolve_user_llm_config returns the raw stored key, which may be a list
    # (rotating keys). Mirror BaseServiceConfiguration's random-choice behavior.
    if isinstance(api_key, list):
        api_key = random.choice(api_key) if api_key else ""
    if not api_key:
        logger.warning(f"[run {workflow_run.id}] No LLM API key, skipping summary")
        return None

    try:
        llm = create_llm_service_from_provider(provider, model, api_key, **kwargs)
        context = LLMContext()
        context.set_messages([{"role": "user", "content": text}])
        summary = await llm.run_inference(
            context, system_instruction=CALL_SUMMARY_SYSTEM_PROMPT
        )
        summary = (summary or "").strip()
        if not summary:
            return None
        logger.info(f"[run {workflow_run.id}] Generated call summary ({len(summary)} chars)")
        return summary
    except Exception as e:
        logger.warning(f"[run {workflow_run.id}] Call summary generation failed: {e}")
        return None
