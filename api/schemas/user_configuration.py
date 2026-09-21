from datetime import datetime

from typing import Literal
from pydantic import BaseModel

from api.services.configuration.registry import (
    EmbeddingsConfig,
    LLMConfig,
    STTConfig,
    TTSConfig,
    S2SConfig,
)


class UserConfiguration(BaseModel):
    llm: LLMConfig | None = None
    stt: STTConfig | None = None
    tts: TTSConfig | None = None
    embeddings: EmbeddingsConfig | None = None
    s2s: S2SConfig | None = None
    active_pipeline: Literal["traditional", "s2s"] = "traditional"
    test_phone_number: str | None = None
    timezone: str | None = None
    last_validated_at: datetime | None = None
