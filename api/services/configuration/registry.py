import random
from enum import Enum, auto
from typing import Annotated, Dict, Literal, Optional, Type, TypeVar, Union

from pydantic import BaseModel, Field, computed_field, field_validator


class ServiceType(Enum):
    LLM = auto()
    TTS = auto()
    STT = auto()
    EMBEDDINGS = auto()
    S2S = auto()


class ServiceProviders(str, Enum):
    OPENAI = "openai"
    DEEPGRAM = "deepgram"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    CARTESIA = "cartesia"
    # NEUPHONIC = "neuphonic"
    ELEVENLABS = "elevenlabs"
    GOOGLE = "google"
    AZURE = "azure"
    DOGRAH = "dograh"
    SARVAM = "sarvam"
    SPEECHMATICS = "speechmatics"
    CAMB = "camb"
    AWS_BEDROCK = "aws_bedrock"
    AWS_POLLY = "aws_polly"
    KOKORO = "kokoro"
    SELF_HOSTED = "self_hosted"


class BaseServiceConfiguration(BaseModel):
    provider: Literal[
        ServiceProviders.OPENAI,
        ServiceProviders.DEEPGRAM,
        ServiceProviders.GROQ,
        ServiceProviders.OPENROUTER,
        ServiceProviders.ELEVENLABS,
        ServiceProviders.GOOGLE,
        ServiceProviders.AZURE,
        ServiceProviders.DOGRAH,
        ServiceProviders.AWS_BEDROCK,
        ServiceProviders.AWS_POLLY,
        ServiceProviders.KOKORO,
        ServiceProviders.SELF_HOSTED,
        ServiceProviders.SARVAM,
    ]
    api_key: Optional[str] | Optional[list[str]] = Field(default=None)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v):
        if v is None:
            return v
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("api_key list must not be empty")
        return v

    def __getattribute__(self, name: str):
        if name == "api_key":
            value = super().__getattribute__(name)
            if value is None:
                return value
            if isinstance(value, list):
                return random.choice(value)
            return value
        return super().__getattribute__(name)

    def get_all_api_keys(self) -> list[str]:
        """Get all API keys as a list (bypasses random selection)."""
        value = super().__getattribute__("api_key")
        if value is None:
            return []
        if isinstance(value, list):
            return list(value)
        return [value]


class BaseLLMConfiguration(BaseServiceConfiguration):
    model: str


class BaseTTSConfiguration(BaseServiceConfiguration):
    model: str


class BaseSTTConfiguration(BaseServiceConfiguration):
    model: str


class BaseEmbeddingsConfiguration(BaseServiceConfiguration):
    model: str


class BaseS2SConfiguration(BaseServiceConfiguration):
    model: str


# Unified registry for all service types
REGISTRY: Dict[ServiceType, Dict[str, Type[BaseServiceConfiguration]]] = {
    ServiceType.LLM: {},
    ServiceType.TTS: {},
    ServiceType.STT: {},
    ServiceType.EMBEDDINGS: {},
    ServiceType.S2S: {},
}

T = TypeVar("T", bound=BaseServiceConfiguration)


def register_service(service_type: ServiceType):
    """Generic decorator for registering service configurations"""

    def decorator(cls: Type[T]) -> Type[T]:
        # Get provider from class attributes or field defaults
        provider = getattr(cls, "provider", None)
        if provider is None:
            # Try to get from model fields
            provider = cls.model_fields.get("provider", None)
            if provider is not None:
                provider = provider.default
        if provider is None:
            raise ValueError(f"Provider not specified for {cls.__name__}")

        REGISTRY[service_type][provider] = cls
        return cls

    return decorator


# Convenience decorators
def register_llm(cls: Type[BaseLLMConfiguration]):
    return register_service(ServiceType.LLM)(cls)


def register_tts(cls: Type[BaseTTSConfiguration]):
    return register_service(ServiceType.TTS)(cls)


def register_stt(cls: Type[BaseSTTConfiguration]):
    return register_service(ServiceType.STT)(cls)


def register_embeddings(cls: Type[BaseEmbeddingsConfiguration]):
    return register_service(ServiceType.EMBEDDINGS)(cls)


def register_s2s(cls: Type[BaseS2SConfiguration]):
    return register_service(ServiceType.S2S)(cls)


###################################################### LLM ########################################################################

# Suggested models for each provider (used for UI dropdown)
OPENAI_MODELS = [
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-3.5-turbo",
]
GOOGLE_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
]
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "deepseek-r1-distill-llama-70b",
    "qwen-qwq-32b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "gemma2-9b-it",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
]
OPENROUTER_MODELS = [
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "anthropic/claude-sonnet-4",
    "google/gemini-2.5-flash",
    "google/gemini-2.0-flash",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat-v3-0324",
]
AZURE_MODELS = ["gpt-4.1-mini"]
DOGRAH_LLM_MODELS = ["default", "accurate", "fast", "lite", "zen"]
AWS_BEDROCK_MODELS = [
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-micro-v1:0",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
]


@register_llm
class OpenAILLMService(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.OPENAI] = ServiceProviders.OPENAI
    model: str = Field(default="gpt-4.1", json_schema_extra={"examples": OPENAI_MODELS})


@register_llm
class GoogleLLMService(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.GOOGLE] = ServiceProviders.GOOGLE
    model: str = Field(
        default="gemini-2.0-flash", json_schema_extra={"examples": GOOGLE_MODELS}
    )


@register_llm
class GroqLLMService(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.GROQ] = ServiceProviders.GROQ
    model: str = Field(
        default="llama-3.3-70b-versatile", json_schema_extra={"examples": GROQ_MODELS}
    )


@register_llm
class OpenRouterLLMConfiguration(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.OPENROUTER] = ServiceProviders.OPENROUTER
    model: str = Field(
        default="openai/gpt-4.1", json_schema_extra={"examples": OPENROUTER_MODELS}
    )

    base_url: str = Field(default="https://openrouter.ai/api/v1")


@register_llm
class AzureLLMService(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.AZURE] = ServiceProviders.AZURE
    model: str = Field(
        default="gpt-4.1-mini", json_schema_extra={"examples": AZURE_MODELS}
    )

    endpoint: str


@register_llm
class DograhLLMService(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.DOGRAH] = ServiceProviders.DOGRAH
    model: str = Field(
        default="default", json_schema_extra={"examples": DOGRAH_LLM_MODELS}
    )


@register_llm
class AWSBedrockLLMConfiguration(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.AWS_BEDROCK] = ServiceProviders.AWS_BEDROCK
    model: str = Field(
        default="us.amazon.nova-pro-v1:0",
        json_schema_extra={"examples": AWS_BEDROCK_MODELS},
    )
    aws_access_key: str = Field(default="")
    aws_secret_key: str = Field(default="")
    aws_region: str = Field(default="us-east-1")
    api_key: str | list[str] | None = Field(default=None)


SELF_HOSTED_LLM_MODELS = ["llama3", "mistral", "phi3", "qwen2", "gemma2", "deepseek-r1"]


@register_llm
class SelfHostedLLMConfiguration(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.SELF_HOSTED] = ServiceProviders.SELF_HOSTED
    model: str = Field(
        default="llama3", json_schema_extra={"examples": SELF_HOSTED_LLM_MODELS}
    )
    base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        description="OpenAI-compatible endpoint (Ollama, vLLM, etc.)",
    )
    api_key: str | list[str] | None = Field(default=None)


SARVAM_LLM_MODELS = ["sarvam-30b", "sarvam-30b-16k", "sarvam-105b", "sarvam-105b-32k"]


@register_llm
class SarvamLLMConfiguration(BaseLLMConfiguration):
    provider: Literal[ServiceProviders.SARVAM] = ServiceProviders.SARVAM
    model: str = Field(
        default="sarvam-30b", json_schema_extra={"examples": SARVAM_LLM_MODELS}
    )


LLMConfig = Annotated[
    Union[
        OpenAILLMService,
        GroqLLMService,
        OpenRouterLLMConfiguration,
        GoogleLLMService,
        AzureLLMService,
        DograhLLMService,
        AWSBedrockLLMConfiguration,
        SelfHostedLLMConfiguration,
        SarvamLLMConfiguration,
    ],
    Field(discriminator="provider"),
]

###################################################### TTS ########################################################################


@register_tts
class DeepgramTTSConfiguration(BaseServiceConfiguration):
    provider: Literal[ServiceProviders.DEEPGRAM] = ServiceProviders.DEEPGRAM
    voice: str = "aura-2-helena-en"

    @computed_field
    @property
    def model(self) -> str:
        # Deepgram model's name is inferred using the voice name.
        # It can either contain aura-2 or aura-1
        if "aura-2" in self.voice:
            return "aura-2"
        elif "aura-1" in self.voice:
            return "aura-1"
        else:
            # Default fallback
            return "aura-2"


ELEVENLABS_TTS_MODELS = ["eleven_flash_v2_5"]


@register_tts
class ElevenlabsTTSConfiguration(BaseServiceConfiguration):
    provider: Literal[ServiceProviders.ELEVENLABS] = ServiceProviders.ELEVENLABS
    voice: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel voice ID
    speed: float = Field(default=1.0, ge=0.1, le=2.0, description="Speed of the voice")
    model: str = Field(
        default="eleven_flash_v2_5",
        json_schema_extra={"examples": ELEVENLABS_TTS_MODELS},
    )


OPENAI_TTS_MODELS = ["gpt-4o-mini-tts"]


@register_tts
class OpenAITTSService(BaseTTSConfiguration):
    provider: Literal[ServiceProviders.OPENAI] = ServiceProviders.OPENAI
    model: str = Field(
        default="gpt-4o-mini-tts", json_schema_extra={"examples": OPENAI_TTS_MODELS}
    )
    voice: str = "alloy"


DOGRAH_TTS_MODELS = ["default"]


@register_tts
class DograhTTSService(BaseTTSConfiguration):
    provider: Literal[ServiceProviders.DOGRAH] = ServiceProviders.DOGRAH
    model: str = Field(
        default="default", json_schema_extra={"examples": DOGRAH_TTS_MODELS}
    )
    voice: str = "default"
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speed of the voice")


CARTESIA_TTS_MODELS = ["sonic-3"]


@register_tts
class CartesiaTTSConfiguration(BaseTTSConfiguration):
    provider: Literal[ServiceProviders.CARTESIA] = ServiceProviders.CARTESIA
    model: str = Field(
        default="sonic-3", json_schema_extra={"examples": CARTESIA_TTS_MODELS}
    )
    voice: str = Field(default="3faa81ae-d3d8-4ab1-9e44-e50e46d33c30")
    speed: float = Field(default=1.0, ge=0.6, le=1.5, description="Speed of the voice")
    volume: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Volume multiplier for generated speech",
    )


SARVAM_TTS_MODELS = ["bulbul:v2", "bulbul:v3"]
SARVAM_V2_VOICES = [
    "anushka",
    "manisha",
    "vidya",
    "arya",
    "abhilash",
    "karun",
    "hitesh",
]
SARVAM_V3_VOICES = [
    "shubh",
    "aditya",
    "ritu",
    "priya",
    "neha",
    "rahul",
    "pooja",
    "rohan",
    "simran",
    "kavya",
    "amit",
    "dev",
    "ishita",
    "shreya",
    "ratan",
    "varun",
    "manan",
    "sumit",
    "roopa",
    "kabir",
    "aayan",
    "ashutosh",
    "advait",
    "amelia",
    "sophia",
    "anand",
    "tanya",
    "tarun",
    "sunny",
    "mani",
    "gokul",
    "vijay",
    "shruti",
    "suhani",
    "mohit",
    "kavitha",
    "rehan",
    "soham",
    "rupali",
]
SARVAM_LANGUAGES = [
    "auto",
    "bn-IN",
    "en-IN",
    "gu-IN",
    "hi-IN",
    "kn-IN",
    "ml-IN",
    "mr-IN",
    "od-IN",
    "pa-IN",
    "ta-IN",
    "te-IN",
    "as-IN",
]


@register_tts
class SarvamTTSConfiguration(BaseTTSConfiguration):
    provider: Literal[ServiceProviders.SARVAM] = ServiceProviders.SARVAM
    model: str = Field(
        default="bulbul:v2", json_schema_extra={"examples": SARVAM_TTS_MODELS}
    )
    voice: str = Field(
        default="anushka",
        json_schema_extra={
            "examples": SARVAM_V2_VOICES,
            "model_options": {
                "bulbul:v2": SARVAM_V2_VOICES,
                "bulbul:v3": SARVAM_V3_VOICES,
            },
        },
    )
    language: str = Field(
        default="hi-IN", json_schema_extra={"examples": SARVAM_LANGUAGES}
    )


CAMB_TTS_MODELS = ["mars-flash", "mars-pro", "mars-instruct"]


@register_tts
class CambTTSConfiguration(BaseTTSConfiguration):
    provider: Literal[ServiceProviders.CAMB] = ServiceProviders.CAMB
    model: str = Field(
        default="mars-flash", json_schema_extra={"examples": CAMB_TTS_MODELS}
    )
    voice: str = Field(default="147320", description="Camb.ai voice ID")
    language: str = Field(default="en-us", description="BCP-47 language code")


AWS_POLLY_ENGINES = ["standard", "neural"]
AWS_POLLY_VOICES = ["Aditi", "Joanna", "Matthew", "Kajal", "Raveena", "Stephen", "Emma", "Brian"]
AWS_POLLY_LANGUAGES = ["auto", "en-IN", "hi-IN", "en-US", "en-GB"]

@register_tts
class AWSPollyTTSConfiguration(BaseTTSConfiguration):
    provider: Literal[ServiceProviders.AWS_POLLY] = ServiceProviders.AWS_POLLY
    model: str = Field(
        default="neural", description="Amazon Polly Engine", json_schema_extra={"examples": AWS_POLLY_ENGINES}
    )
    voice: str = Field(
        default="Kajal", json_schema_extra={"examples": AWS_POLLY_VOICES}
    )
    language: str = Field(
        default="auto", description="Use auto for seamless bilingual support.", json_schema_extra={"examples": AWS_POLLY_LANGUAGES}
    )
    aws_access_key: str = Field(default="")
    aws_region: str = Field(default="ap-south-1")
    api_key: str | list[str] = Field(default="")

KOKORO_TTS_MODELS = ["kokoro-v1.0"]  # local ONNX model
KOKORO_TTS_VOICES = ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael"]
KOKORO_TTS_LANGUAGES = ["auto", "en-us", "en-gb", "fr", "hi", "es", "ja", "zh", "pt", "it"]

@register_tts
class KokoroTTSConfiguration(BaseTTSConfiguration):
    provider: Literal[ServiceProviders.KOKORO] = ServiceProviders.KOKORO
    model: str = Field(
        default="kokoro-v1.0", description="Kokoro ONNX Model", json_schema_extra={"examples": KOKORO_TTS_MODELS}
    )
    voice: str = Field(
        default="af_heart", json_schema_extra={"examples": KOKORO_TTS_VOICES}
    )
    language: str = Field(
        default="auto", description="Language for synthesis. Auto enables bilingual en/hi switching.", json_schema_extra={"examples": KOKORO_TTS_LANGUAGES}
    )
    speed: float = Field(
        default=1.0, description="Playback speed. Lower values (e.g., 0.9) can stretch vowels making it sound more natural."
    )
    api_key: str | list[str] = Field(default="")  # Ignored as it runs locally


TTSConfig = Annotated[
    Union[
        DeepgramTTSConfiguration,
        OpenAITTSService,
        ElevenlabsTTSConfiguration,
        CartesiaTTSConfiguration,
        DograhTTSService,
        SarvamTTSConfiguration,
        CambTTSConfiguration,
        AWSPollyTTSConfiguration,
        KokoroTTSConfiguration,
    ],
    Field(discriminator="provider"),
]

###################################################### STT ########################################################################


DEEPGRAM_STT_MODELS = ["nova-3-general", "flux-general-en"]
DEEPGRAM_LANGUAGES = [
    "multi",
    "ar",
    "ar-AE",
    "ar-SA",
    "ar-QA",
    "ar-KW",
    "ar-SY",
    "ar-LB",
    "ar-PS",
    "ar-JO",
    "ar-EG",
    "ar-SD",
    "ar-TD",
    "ar-MA",
    "ar-DZ",
    "ar-TN",
    "ar-IQ",
    "ar-IR",
    "be",
    "bn",
    "bs",
    "bg",
    "ca",
    "cs",
    "da",
    "da-DK",
    "de",
    "de-CH",
    "el",
    "en",
    "en-US",
    "en-AU",
    "en-GB",
    "en-IN",
    "en-NZ",
    "es",
    "es-419",
    "et",
    "fa",
    "fi",
    "fr",
    "fr-CA",
    "he",
    "hi",
    "hr",
    "hu",
    "id",
    "it",
    "ja",
    "kn",
    "ko",
    "ko-KR",
    "lt",
    "lv",
    "mk",
    "mr",
    "ms",
    "nl",
    "nl-BE",
    "no",
    "pl",
    "pt",
    "pt-BR",
    "pt-PT",
    "ro",
    "ru",
    "sk",
    "sl",
    "sr",
    "sv",
    "sv-SE",
    "ta",
    "te",
    "th",
    "tl",
    "tr",
    "uk",
    "ur",
    "vi",
    "zh-CN",
    "zh-TW",
]


@register_stt
class DeepgramSTTConfiguration(BaseSTTConfiguration):
    provider: Literal[ServiceProviders.DEEPGRAM] = ServiceProviders.DEEPGRAM
    model: str = Field(
        default="nova-3-general", json_schema_extra={"examples": DEEPGRAM_STT_MODELS}
    )
    language: str = Field(
        default="multi",
        json_schema_extra={
            "examples": DEEPGRAM_LANGUAGES,
            "model_options": {
                "nova-3-general": DEEPGRAM_LANGUAGES,
                "flux-general-en": ["en"],
            },
        },
    )


CARTESIA_STT_MODELS = ["ink-whisper"]


@register_stt
class CartesiaSTTConfiguration(BaseSTTConfiguration):
    provider: Literal[ServiceProviders.CARTESIA] = ServiceProviders.CARTESIA
    model: str = Field(
        default="ink-whisper", json_schema_extra={"examples": CARTESIA_STT_MODELS}
    )


OPENAI_STT_MODELS = ["gpt-4o-transcribe"]


@register_stt
class OpenAISTTConfiguration(BaseSTTConfiguration):
    provider: Literal[ServiceProviders.OPENAI] = ServiceProviders.OPENAI
    model: str = Field(
        default="gpt-4o-transcribe", json_schema_extra={"examples": OPENAI_STT_MODELS}
    )


# Dograh STT Service
DOGRAH_STT_MODELS = ["default"]
DOGRAH_STT_LANGUAGES = DEEPGRAM_LANGUAGES


@register_stt
class DograhSTTService(BaseSTTConfiguration):
    provider: Literal[ServiceProviders.DOGRAH] = ServiceProviders.DOGRAH
    model: str = Field(
        default="default", json_schema_extra={"examples": DOGRAH_STT_MODELS}
    )
    language: str = Field(
        default="multi", json_schema_extra={"examples": DOGRAH_STT_LANGUAGES}
    )


# Sarvam STT Service
SARVAM_STT_MODELS = ["saarika:v2.5", "saaras:v2", "saaras:v3"]


@register_stt
class SarvamSTTConfiguration(BaseSTTConfiguration):
    provider: Literal[ServiceProviders.SARVAM] = ServiceProviders.SARVAM
    model: str = Field(
        default="saarika:v2.5", json_schema_extra={"examples": SARVAM_STT_MODELS}
    )
    language: str = Field(
        default="hi-IN", json_schema_extra={"examples": SARVAM_LANGUAGES}
    )


# Speechmatics STT Service
SPEECHMATICS_STT_LANGUAGES = [
    "en",
    "es",
    "fr",
    "de",
    "it",
    "pt",
    "nl",
    "ja",
    "ko",
    "zh",
    "ru",
    "ar",
    "hi",
    "pl",
    "tr",
    "vi",
    "th",
    "id",
    "ms",
    "sv",
    "da",
    "no",
    "fi",
]


@register_stt
class SpeechmaticsSTTConfiguration(BaseSTTConfiguration):
    provider: Literal[ServiceProviders.SPEECHMATICS] = ServiceProviders.SPEECHMATICS
    model: str = Field(
        default="enhanced", description="Operating point: standard or enhanced"
    )
    language: str = Field(
        default="en", json_schema_extra={"examples": SPEECHMATICS_STT_LANGUAGES}
    )


# Groq STT Service (Whisper via Groq LPU)
GROQ_STT_MODELS = ["whisper-large-v3-turbo", "whisper-large-v3"]
GROQ_STT_LANGUAGES = [
    "auto",
    "en+hi",
    "af",
    "ar",
    "hy",
    "az",
    "be",
    "bs",
    "bg",
    "ca",
    "zh",
    "hr",
    "cs",
    "da",
    "nl",
    "en",
    "et",
    "fi",
    "fr",
    "gl",
    "de",
    "el",
    "he",
    "hi",
    "hu",
    "is",
    "id",
    "it",
    "ja",
    "kn",
    "kk",
    "ko",
    "lv",
    "lt",
    "mk",
    "ms",
    "mr",
    "mi",
    "ne",
    "no",
    "fa",
    "pl",
    "pt",
    "ro",
    "ru",
    "sr",
    "sk",
    "sl",
    "es",
    "sw",
    "sv",
    "tl",
    "ta",
    "th",
    "tr",
    "uk",
    "ur",
    "vi",
    "cy",
]


@register_stt
class GroqSTTConfiguration(BaseSTTConfiguration):
    provider: Literal[ServiceProviders.GROQ] = ServiceProviders.GROQ
    model: str = Field(
        default="whisper-large-v3-turbo",
        json_schema_extra={"examples": GROQ_STT_MODELS},
    )
    language: str = Field(
        default="auto",
        json_schema_extra={"examples": GROQ_STT_LANGUAGES},
    )


STTConfig = Annotated[
    Union[
        DeepgramSTTConfiguration,
        CartesiaSTTConfiguration,
        OpenAISTTConfiguration,
        DograhSTTService,
        SpeechmaticsSTTConfiguration,
        SarvamSTTConfiguration,
        GroqSTTConfiguration,
    ],
    Field(discriminator="provider"),
]

###################################################### EMBEDDINGS ########################################################################

OPENAI_EMBEDDING_MODELS = ["text-embedding-3-small"]


@register_embeddings
class OpenAIEmbeddingsConfiguration(BaseEmbeddingsConfiguration):
    provider: Literal[ServiceProviders.OPENAI] = ServiceProviders.OPENAI
    model: str = Field(
        default="text-embedding-3-small",
        json_schema_extra={"examples": OPENAI_EMBEDDING_MODELS},
    )


OPENROUTER_EMBEDDING_MODELS = ["openai/text-embedding-3-small", "nvidia/llama-nemotron-embed-vl-1b-v2:free"]


@register_embeddings
class OpenRouterEmbeddingsConfiguration(BaseEmbeddingsConfiguration):
    provider: Literal[ServiceProviders.OPENROUTER] = ServiceProviders.OPENROUTER
    model: str = Field(
        default="openai/text-embedding-3-small",
        json_schema_extra={"examples": OPENROUTER_EMBEDDING_MODELS},
    )

    base_url: str = Field(default="https://openrouter.ai/api/v1")


GOOGLE_EMBEDDING_MODELS = ["gemini-embedding-001", "text-embedding-004"]


@register_embeddings
class GoogleEmbeddingsConfiguration(BaseEmbeddingsConfiguration):
    provider: Literal[ServiceProviders.GOOGLE] = ServiceProviders.GOOGLE
    model: str = Field(
        default="gemini-embedding-001",
        json_schema_extra={"examples": GOOGLE_EMBEDDING_MODELS},
    )





EmbeddingsConfig = Annotated[
    Union[
        OpenAIEmbeddingsConfiguration,
        OpenRouterEmbeddingsConfiguration,
        GoogleEmbeddingsConfiguration,
    ],
    Field(discriminator="provider"),
]

###################################################### S2S ########################################################################

GEMINI_S2S_MODELS = [
    "gemini-3.1-flash-live-preview",
    "gemini-live-2.5-flash-native-audio",
    "gemini-2.0-flash-exp",
    "gemini-2.5-flash",
]

GEMINI_S2S_VOICES = ["Aoede", "Charon", "Fenrir", "Kore", "Puck"]

@register_s2s
class GoogleS2SConfiguration(BaseS2SConfiguration):
    provider: Literal[ServiceProviders.GOOGLE] = ServiceProviders.GOOGLE
    model: str = Field(
        default="gemini-3.1-flash-live-preview",
        json_schema_extra={"examples": GEMINI_S2S_MODELS},
    )
    voice: str = Field(
        default="Puck",
        json_schema_extra={"examples": GEMINI_S2S_VOICES},
    )

S2SConfig = Annotated[
    Union[GoogleS2SConfiguration],
    Field(discriminator="provider"),
]

ServiceConfig = Annotated[
    Union[LLMConfig, TTSConfig, STTConfig, EmbeddingsConfig, S2SConfig],
    Field(discriminator="provider"),
]
