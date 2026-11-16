"""Bound post-call insights so a slow local model cannot stall completion.

The local sentiment model is CPU-heavy and used to run on the event loop's
default executor, which is shared with DNS lookups and MinIO/S3 blocking calls.
A stuck inference therefore took the whole completion job down with it *and*
starved unrelated I/O. These tests pin down the timeout and the fail-fast model
loading behaviour.
"""

import asyncio
import sys
from types import ModuleType

import pytest

from api.services import call_insights

TRANSCRIPT = "caller: hello, I would like a quote\nagent: sure, one moment"


@pytest.fixture(autouse=True)
def _reset_sentiment_state(monkeypatch):
    monkeypatch.setattr(call_insights, "_sentiment_pipeline", None)
    monkeypatch.setattr(call_insights, "_sentiment_load_failed", False)
    monkeypatch.setattr(call_insights, "SENTIMENT_TIMEOUT_SECONDS", 0.05)


async def test_stuck_sentiment_model_does_not_block_insights(monkeypatch):
    async def _extract(*_args, **_kwargs):
        return {"callback_at_iso": None, "action_items": ["Send the quote"]}

    def _slow_classify(_text):
        import time

        time.sleep(0.2)  # simulates an inference that outlives its budget
        return "Interested"

    monkeypatch.setattr(call_insights, "extract_callback_and_actions", _extract)
    monkeypatch.setattr(call_insights, "classify_sentiment", _slow_classify)

    insights = await asyncio.wait_for(
        call_insights.generate_call_insights(None, TRANSCRIPT, "iso", "UTC"),
        timeout=1.0,
    )

    assert insights["sentiment"] is None
    assert insights["action_items"] == ["Send the quote"]


async def test_sentiment_is_skipped_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(call_insights, "_sentiment_load_failed", True)

    assert await call_insights.classify_sentiment_async(TRANSCRIPT) is None


def test_failed_model_load_is_not_retried_per_call(monkeypatch):
    attempts = []

    def _failing_pipeline(*_args, **_kwargs):
        attempts.append(1)
        raise RuntimeError("model hub unreachable")

    fake_transformers = ModuleType("transformers")
    fake_transformers.pipeline = _failing_pipeline
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    # classify_sentiment never raises; the load failure is swallowed.
    assert call_insights.classify_sentiment(TRANSCRIPT) is None
    assert call_insights.classify_sentiment(TRANSCRIPT) is None
    assert len(attempts) == 1
