#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Sarvam LLM service implementation.

This module provides an OpenAI-compatible interface for interacting with Sarvam's API,
extending the base OpenAI LLM service functionality. Sarvam's API is OpenAI-compatible
but does not support certain OpenAI-specific parameters like stream_options,
max_completion_tokens, and service_tier.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from loguru import logger

from pipecat.services.openai.base_llm import OpenAILLMSettings
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.settings import _warn_deprecated_param


# Parameters that Sarvam's API does not support
_UNSUPPORTED_PARAMS = frozenset(
    {
        "stream_options",
        "max_completion_tokens",
        "service_tier",
    }
)


@dataclass
class SarvamLLMSettings(OpenAILLMSettings):
    """Settings for SarvamLLMService.

    Extends OpenAI settings with Sarvam-specific features:
    - wiki_grounding: Enable Wikipedia-based grounding for responses
    - reasoning_effort: Control reasoning depth ("low", "medium", "high")
    """

    model: str = "sarvam-30b"
    wiki_grounding: Optional[bool] = None
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = None


class SarvamLLMService(OpenAILLMService):
    """A service for interacting with Sarvam's API using the OpenAI-compatible interface.

    This service extends OpenAILLMService to connect to Sarvam's API endpoint while
    filtering out unsupported OpenAI-specific parameters and supporting Sarvam-specific
    features like wiki_grounding and reasoning_effort.
    """

    Settings = SarvamLLMSettings
    _settings: SarvamLLMSettings

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: str = "https://api.sarvam.ai/v1",
        settings: Optional[SarvamLLMSettings] = None,
        **kwargs,
    ):
        """Initialize the Sarvam LLM service.

        Args:
            api_key: The API key for accessing Sarvam's API.
            model: The model identifier to use. Defaults to "sarvam-30b".
            base_url: The base URL for Sarvam API. Defaults to "https://api.sarvam.ai/v1".
            settings: Runtime-updatable settings.
            **kwargs: Additional keyword arguments passed to OpenAILLMService.
        """
        default_settings = SarvamLLMSettings(model="sarvam-30b")

        if model is not None:
            _warn_deprecated_param("model", SarvamLLMSettings, "model")
            default_settings.model = model

        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            api_key=api_key,
            base_url=base_url,
            settings=default_settings,
            **kwargs,
        )

    def create_client(self, api_key=None, base_url=None, **kwargs):
        """Create a Sarvam API client."""
        logger.debug(f"Creating Sarvam client with api {base_url}")
        return super().create_client(api_key, base_url, **kwargs)

    def build_chat_completion_params(self, params_from_context: Dict[str, Any]) -> Dict[str, Any]:
        """Builds chat parameters, stripping unsupported OpenAI params for Sarvam.

        Removes stream_options, max_completion_tokens, and service_tier which
        are not supported by Sarvam's API. Also injects Sarvam-specific params
        like wiki_grounding and reasoning_effort when configured.

        On the initial greeting turn (no user messages yet), tools are stripped
        to prevent Sarvam from eagerly calling functions before a user query
        exists, which would deadlock the pipeline.

        Args:
            params_from_context: Parameters from the LLM context.

        Returns:
            Transformed parameters ready for the Sarvam API call.
        """
        params = super().build_chat_completion_params(params_from_context)

        # Remove unsupported OpenAI parameters
        for key in _UNSUPPORTED_PARAMS:
            params.pop(key, None)

        # Strip tools on the initial greeting turn (no user messages yet).
        # Sarvam-30b eagerly calls functions even when there is no user query,
        # which causes a deadlock: the function call is deferred until TTS
        # completes, but TTS has nothing to speak, so the pipeline hangs and
        # the user stays muted forever.
        messages = params.get("messages", [])
        has_user_message = any(m.get("role") == "user" for m in messages)
        if not has_user_message:
            params.pop("tools", None)
            params.pop("tool_choice", None)

        # Inject Sarvam-specific parameters
        wiki_grounding = getattr(self._settings, "wiki_grounding", None)
        if wiki_grounding is not None:
            params["wiki_grounding"] = wiki_grounding

        reasoning_effort = getattr(self._settings, "reasoning_effort", None)
        if reasoning_effort is not None:
            params["reasoning_effort"] = reasoning_effort

        return params

    async def _process_context(self, context):
        """Process context, ensuring function calls are never deferred.

        Sarvam-30b often returns minimal/empty text alongside tool calls. The
        base class defers function calls until BotStoppedSpeakingFrame arrives,
        but when TTS has nothing substantial to speak, that frame never fires
        and the pipeline deadlocks (user stays muted forever).

        We override to: run the base processing, then immediately execute any
        pending function calls that were deferred, preventing the deadlock.
        """
        await super()._process_context(context)

        # If base class deferred any function calls, execute them now
        if self._pending_function_calls:
            logger.debug(
                f"{self}: Immediately executing {len(self._pending_function_calls)} "
                f"function calls (preventing Sarvam TTS deadlock)"
            )
            await self.run_function_calls(self._pending_function_calls)
            self._pending_function_calls = []
