"""Post-call insights: callback extraction, action items, and sentiment.

- Callback requests + action items come from the agent's configured LLM
  (one strict-JSON call), mirroring ``call_summarization.py``.
- Sentiment (Interested / Not interested / Neutral) comes from a dedicated
  local multilingual NLP model (zero-shot NLI) — no external API calls.
"""

import asyncio
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from api.services.pipecat.service_factory import create_llm_service_from_provider
from api.services.workflow.qa.llm_config import resolve_user_llm_config
from pipecat.processors.aggregators.llm_context import LLMContext

EXTRACTION_SYSTEM_PROMPT = (
    "You analyze a phone call transcript between a human caller and an AI voice agent. "
    "Return STRICT JSON only with exactly these keys:\n"
    '{"callback_at_iso": string|null, "action_items": string[]}\n'
    "Rules:\n"
    "- callback_at_iso: the exact ISO-8601 datetime the caller asked to be called back "
    "(resolve relative phrases like 'after 4 PM' or 'next Tuesday' against the call time "
    "and timezone given below). Null when no callback was requested.\n"
    "- action_items: concrete follow-up tasks or commitments from the call "
    "(e.g. 'Email the quote to the customer'). Empty array when none.\n"
    "- No markdown, no commentary, JSON only."
)

MAX_TRANSCRIPT_CHARS = 12000
MIN_TRANSCRIPT_CHARS = 20

# Dedicated local NLP model for caller-intent classification. Multilingual
# (Hindi/English/Spanish/…) zero-shot NLI; stays fully on-device.
SENTIMENT_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
SENTIMENT_LABELS = ["interested", "not interested", "neutral"]
SENTIMENT_DISPLAY = {
    "interested": "Interested",
    "not interested": "Not interested",
    "neutral": "Neutral",
}
SENTIMENT_MIN_SCORE = 0.4
SENTIMENT_MAX_CHARS = 4000

# The local model is CPU-heavy. Run it on exactly one dedicated thread so that
# concurrent completion jobs cannot oversubscribe the container, and so the
# loop's default executor (DNS lookups, MinIO/S3 blocking calls) stays free.
# Sharing that executor with the model used to starve unrelated I/O: source
# syncs failed with MinIO connect timeouts while insights were running.
_SENTIMENT_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="sentiment"
)
SENTIMENT_TIMEOUT_SECONDS = 120.0
EXTRACTION_TIMEOUT_SECONDS = 60.0

_sentiment_pipeline = None
_sentiment_load_failed = False
_sentiment_lock = threading.Lock()


def _truncate(transcript: str, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    text = (transcript or "").strip()
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]"
    return text


def _pick_key(value):
    if isinstance(value, list):
        return random.choice(value) if value else ""
    return value or ""


async def extract_callback_and_actions(
    workflow_run, transcript_text: str, call_time_iso: str, user_tz: str
) -> dict:
    """LLM extraction of callback time + action items. Never raises."""
    text = _truncate(transcript_text)
    if len(text) < MIN_TRANSCRIPT_CHARS:
        return {"callback_at_iso": None, "action_items": []}

    try:
        provider, model, api_key, kwargs = await resolve_user_llm_config(workflow_run)
    except Exception as e:
        logger.warning(f"[run {workflow_run.id}] Failed to resolve LLM config: {e}")
        return {"callback_at_iso": None, "action_items": []}

    api_key = _pick_key(api_key)
    if not api_key:
        return {"callback_at_iso": None, "action_items": []}

    prompt = (
        f"Call time: {call_time_iso}\n"
        f"Caller timezone: {user_tz}\n\n"
        f"Transcript:\n{text}"
    )
    try:
        llm = create_llm_service_from_provider(provider, model, api_key, **kwargs)
        context = LLMContext()
        context.set_messages([{"role": "user", "content": prompt}])
        raw = await llm.run_inference(
            context, system_instruction=EXTRACTION_SYSTEM_PROMPT
        )
        raw = (raw or "").strip()
        # Tolerate code fences.
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        data = json.loads(raw)
        callback_at = data.get("callback_at_iso")
        actions = data.get("action_items") or []
        if not isinstance(actions, list):
            actions = []
        actions = [str(a).strip() for a in actions if str(a).strip()][:20]
        if callback_at is not None:
            callback_at = str(callback_at).strip() or None
        logger.info(
            f"[run {workflow_run.id}] Extracted callback={callback_at} "
            f"actions={len(actions)}"
        )
        return {"callback_at_iso": callback_at, "action_items": actions}
    except Exception as e:
        logger.warning(f"[run {workflow_run.id}] Insight extraction failed: {e}")
        return {"callback_at_iso": None, "action_items": []}


def _load_sentiment_pipeline():
    """Lazy singleton (first call downloads/loads ~1GB, then cached).

    A failed load is remembered: retrying the (often network-bound) download on
    every transcript would block the worker for minutes per call.
    """
    global _sentiment_pipeline, _sentiment_load_failed
    if _sentiment_pipeline is not None or _sentiment_load_failed:
        return _sentiment_pipeline
    with _sentiment_lock:
        if _sentiment_pipeline is not None or _sentiment_load_failed:
            return _sentiment_pipeline
        try:
            from transformers import pipeline

            try:
                import torch

                # Inference is serialized on one thread, so more intra-op
                # threads only cause contention with the event loop.
                torch.set_num_threads(1)
            except Exception as e:
                logger.debug(f"Could not limit torch threads: {e}")

            logger.info(f"Loading local sentiment model {SENTIMENT_MODEL_ID} ...")
            _sentiment_pipeline = pipeline(
                "zero-shot-classification",
                model=SENTIMENT_MODEL_ID,
                device=-1,  # CPU
            )
            logger.info("Local sentiment model loaded")
        except Exception as e:
            _sentiment_load_failed = True
            logger.error(
                f"Could not load local sentiment model {SENTIMENT_MODEL_ID}: {e}. "
                "Sentiment will be skipped until the worker restarts."
            )
        return _sentiment_pipeline


def warm_sentiment_model() -> None:
    """Load the local sentiment model ahead of the first call.

    Loading takes ~2 minutes on CPU; warming it from the worker's startup hook
    keeps that cost out of the workflow-completion job's timeout.
    """
    _load_sentiment_pipeline()


async def warm_sentiment_model_async() -> None:
    """Warm the model on its own thread instead of the loop's default executor."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_SENTIMENT_EXECUTOR, warm_sentiment_model)


def classify_sentiment(transcript_text: str) -> str | None:
    """Classify caller intent locally. Returns display label or None."""
    text = _truncate(transcript_text, SENTIMENT_MAX_CHARS)
    if len(text) < MIN_TRANSCRIPT_CHARS:
        return None
    classifier = _load_sentiment_pipeline()
    if classifier is None:
        return None
    try:
        result = classifier(
            text,
            candidate_labels=SENTIMENT_LABELS,
            hypothesis_template="The caller is {}.",
            multi_label=False,
        )
        top_label = result["labels"][0]
        top_score = float(result["scores"][0])
        logger.info(
            f"Sentiment classified as '{top_label}' (score={top_score:.2f})"
        )
        if top_score < SENTIMENT_MIN_SCORE:
            return None
        return SENTIMENT_DISPLAY.get(top_label)
    except Exception as e:
        logger.warning(f"Local sentiment classification failed: {e}")
        return None


async def classify_sentiment_async(transcript_text: str) -> str | None:
    """Classify sentiment without letting the caller hang on the local model.

    Runs on the dedicated single-thread executor (never the loop's default one)
    and gives up after ``SENTIMENT_TIMEOUT_SECONDS`` so a pathological
    transcript cannot consume the whole completion job.
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                _SENTIMENT_EXECUTOR, classify_sentiment, transcript_text
            ),
            timeout=SENTIMENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"Local sentiment classification exceeded "
            f"{SENTIMENT_TIMEOUT_SECONDS:.0f}s; skipping sentiment for this call"
        )
        return None
    except Exception as e:
        logger.warning(f"Local sentiment classification failed: {e}")
        return None


async def generate_call_insights(
    workflow_run, transcript_text: str, call_time_iso: str, user_tz: str
) -> dict:
    """Run extraction (LLM) + sentiment (local NLP). Never raises."""
    extraction, sentiment = await asyncio.gather(
        asyncio.wait_for(
            extract_callback_and_actions(
                workflow_run, transcript_text, call_time_iso, user_tz
            ),
            timeout=EXTRACTION_TIMEOUT_SECONDS,
        ),
        classify_sentiment_async(transcript_text),
        return_exceptions=True,
    )
    if isinstance(extraction, Exception):
        logger.warning(f"Insight extraction errored: {extraction}")
        extraction = {"callback_at_iso": None, "action_items": []}
    if isinstance(sentiment, Exception):
        logger.warning(f"Sentiment errored: {sentiment}")
        sentiment = None
    return {
        "callback_at_iso": extraction.get("callback_at_iso"),
        "action_items": extraction.get("action_items", []),
        "sentiment": sentiment,
    }
