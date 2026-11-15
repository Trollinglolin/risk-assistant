"""Provider adapters. Free providers first; Anthropic optional.

Choose with env LLM_PROVIDER (default: gemini, the one the eval was run on). Model with LLM_MODEL. Keys:
  groq        GROQ_API_KEY        https://console.groq.com          (free tier)
  gemini      GEMINI_API_KEY      https://aistudio.google.com       (free tier)
  openrouter  OPENROUTER_API_KEY  https://openrouter.ai  (':free' models)
  ollama      none                local `ollama serve`             (free, offline)
  anthropic   ANTHROPIC_API_KEY   paid
Model defaults below are only starting points; check each provider's current model list
for one that supports tool/function calling and set LLM_MODEL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY",
               "gemini-3.5-flash-lite"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                   "openai/gpt-oss-120b:free"),
    "ollama": ("http://localhost:11434/v1", None, "qwen3:8b"),
    "anthropic": (None, "ANTHROPIC_API_KEY", "claude-opus-5-5"),
}


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str | None
    api_key: str | None

    @classmethod
    def from_env(cls, provider: str | None = None, model: str | None = None) -> LLMConfig:
        from dotenv import load_dotenv

        load_dotenv()
        provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).lower()
        if provider not in PRESETS:
            raise ValueError(f"unknown LLM_PROVIDER {provider!r}; choose from {list(PRESETS)}")
        base_url, key_env, default_model = PRESETS[provider]
        base_url = os.getenv("LLM_BASE_URL", base_url)
        api_key = os.getenv(key_env) if key_env else "ollama"
        if key_env and not api_key:
            raise RuntimeError(f"{key_env} is not set (put it in .env)")
        return cls(provider, model or os.getenv("LLM_MODEL", default_model), base_url, api_key)
