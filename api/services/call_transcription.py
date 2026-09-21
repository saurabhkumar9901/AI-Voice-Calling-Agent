"""Fallback transcription of call recordings with speaker diarization.

Used when the live pipeline transcript is missing or too short (e.g. S2S
pipelines where assistant audio isn't captured as text events) but a call
recording exists. The resulting transcript feeds the normal summary step.

Key priority mirrors the user's configured services:
  1. Google (Gemini multimodal, works with the LLM or S2S Google key)
  2. Deepgram prerecorded nova-3 with diarization (needs a Deepgram STT key)
  3. OpenAI transcription (no diarization, plain text fallback)
"""

import asyncio
import os
import random

from loguru import logger

from api.services.workflow.qa.llm_config import resolve_user_llm_config

DIARIZE_PROMPT = (
    "Transcribe this phone call recording between a human caller and an AI voice agent. "
    "Distinguish the two speakers. Output one utterance per line in exactly this format:\n"
    "[MM:SS] User: <what the human caller said>\n"
    "[MM:SS] Agent: <what the AI agent said>\n"
    "Use timestamps from the start of the audio. Do not add commentary, only the transcript lines."
)

# Don't send huge files inline to multimodal APIs (59s @16kHz mono ~2MB; cap at ~15min).
MAX_AUDIO_BYTES = 30 * 1024 * 1024
MIN_AUDIO_BYTES = 10 * 1024


def _pick_key(value):
    if isinstance(value, list):
        return random.choice(value) if value else ""
    return value or ""


async def _resolve_keys(workflow_run):
    """Return (google_key, google_model, deepgram_key, openai_key)."""
    google_key, google_model = "", ""
    deepgram_key, openai_key = "", ""
    try:
        provider, model, api_key, _kwargs = await resolve_user_llm_config(workflow_run)
        api_key = _pick_key(api_key)
        if provider == "google" and api_key:
            google_key, google_model = api_key, model
        elif provider == "openai" and api_key:
            openai_key = api_key
    except Exception as e:
        logger.debug(f"Could not resolve LLM config for transcription: {e}")

    # STT config may hold a Deepgram/OpenAI key even when LLM is another provider.
    try:
        user_id = None
        if workflow_run.workflow and workflow_run.workflow.user:
            user_id = workflow_run.workflow.user.id
        if user_id:
            from api.db import db_client

            user_config = await db_client.get_user_configurations(user_id)
            stt = getattr(user_config, "stt", None)
            if stt is not None:
                stt_key = _pick_key(getattr(stt, "api_key", ""))
                if getattr(stt, "provider", "") == "deepgram" and stt_key:
                    deepgram_key = stt_key
                elif getattr(stt, "provider", "") == "openai" and stt_key:
                    openai_key = openai_key or stt_key
            s2s = getattr(user_config, "s2s", None)
            if not google_key and s2s is not None and getattr(s2s, "provider", "") == "google":
                s2s_key = _pick_key(getattr(s2s, "api_key", ""))
                if s2s_key:
                    google_key = s2s_key
    except Exception as e:
        logger.debug(f"Could not resolve STT/S2S config for transcription: {e}")

    return google_key, google_model or "gemini-2.0-flash", deepgram_key, openai_key


async def _transcribe_with_google(audio_path: str, api_key: str, model: str):
    from google import genai
    from google.genai import types

    with open(audio_path, "rb") as f:
        data = f.read()

    def _call():
        client = genai.Client(api_key=api_key)
        return client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=data, mime_type="audio/wav"),
                DIARIZE_PROMPT,
            ],
        )

    response = await asyncio.to_thread(_call)
    texts = []
    for cand in response.candidates or []:
        for part in (cand.content.parts or []):
            if part.text:
                texts.append(part.text)
    return "\n".join(texts).strip() or None


async def _transcribe_with_deepgram(audio_path: str, api_key: str):
    from deepgram import DeepgramClient

    with open(audio_path, "rb") as f:
        data = f.read()

    def _call():
        client = DeepgramClient(api_key=api_key)
        return client.listen.v1.media.transcribe_file(
            request=data,
            model="nova-3",
            smart_format=True,
            punctuate=True,
            diarize=True,
            utterances=True,
        )

    response = await asyncio.to_thread(_call)
    lines = []
    try:
        for utt in response.results.utterances or []:
            speaker = getattr(utt, "speaker", "?")
            lines.append(f"User (speaker {speaker}): {utt.transcript}")
    except AttributeError:
        pass
    if not lines:
        try:
            alt = response.results.channels[0].alternatives[0]
            if alt.transcript:
                lines.append(alt.transcript)
        except (AttributeError, IndexError):
            pass
    return "\n".join(lines).strip() or None


async def _transcribe_with_openai(audio_path: str, api_key: str):
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    with open(audio_path, "rb") as f:
        result = await client.audio.transcriptions.create(
            model="whisper-1", file=(os.path.basename(audio_path), f, "audio/wav")
        )
    text = getattr(result, "text", "") or ""
    return text.strip() or None


async def transcribe_call_audio(audio_path: str, workflow_run) -> str | None:
    """Transcribe a call recording with speaker labels.

    Returns transcript text or None. Never raises.
    """
    try:
        size = os.path.getsize(audio_path)
    except OSError:
        return None
    if size < MIN_AUDIO_BYTES or size > MAX_AUDIO_BYTES:
        logger.info(
            f"[run {workflow_run.id}] Skipping audio transcription (size {size} bytes)"
        )
        return None

    google_key, google_model, deepgram_key, openai_key = await _resolve_keys(workflow_run)

    if google_key:
        try:
            text = await _transcribe_with_google(audio_path, google_key, google_model)
            if text:
                logger.info(f"[run {workflow_run.id}] Transcribed audio via Gemini ({len(text)} chars)")
                return text
        except Exception as e:
            logger.warning(f"[run {workflow_run.id}] Gemini transcription failed: {e}")

    if deepgram_key:
        try:
            text = await _transcribe_with_deepgram(audio_path, deepgram_key)
            if text:
                logger.info(f"[run {workflow_run.id}] Transcribed audio via Deepgram ({len(text)} chars)")
                return text
        except Exception as e:
            logger.warning(f"[run {workflow_run.id}] Deepgram transcription failed: {e}")

    if openai_key:
        try:
            text = await _transcribe_with_openai(audio_path, openai_key)
            if text:
                logger.info(f"[run {workflow_run.id}] Transcribed audio via OpenAI ({len(text)} chars)")
                return text
        except Exception as e:
            logger.warning(f"[run {workflow_run.id}] OpenAI transcription failed: {e}")

    logger.warning(f"[run {workflow_run.id}] No transcription key available, skipping audio transcription")
    return None
