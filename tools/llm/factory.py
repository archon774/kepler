"""``parse_spec`` and ``build_backend`` -- ``provider/model`` spec parsing and
backend construction.

This module owns the credential/endpoint binding rule (S3). Resolution order,
and no other: an explicit argument beats the environment, which beats the class
defaults. A provider key from the environment reaches only that provider's
default host; a non-default base URL needs a key passed explicitly alongside
it, or no ``Authorization`` header is sent at all.

Adapter imports are function-local so ``import tools.llm`` stays cheap.
"""

from __future__ import annotations

import os
from typing import Any

from tools.llm.base import ModelBackend

__all__ = ["parse_spec", "build_backend", "RECOGNIZED_PROVIDERS"]

RECOGNIZED_PROVIDERS = ("anthropic", "openai", "ollama", "gemini")

_OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def parse_spec(spec: str) -> tuple[str, str]:
    """Split ``provider/model`` on the **first slash only** -- Ollama model
    names contain colons and OpenAI-compatible model ids can contain slashes
    (``openai/meta-llama/Llama-3-8b`` is provider ``openai``, model
    ``meta-llama/Llama-3-8b``)."""

    if "/" not in spec:
        raise ValueError(
            f"backend spec must be 'provider/model', got {spec!r}"
        )
    provider, model = spec.split("/", 1)
    if not provider or not model:
        raise ValueError(f"backend spec must be 'provider/model', got {spec!r}")
    return provider, model


def build_backend(
    spec: str | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    transport: Any = None,
    thinking_budget: int | None = None,
) -> ModelBackend:
    """Construct the backend named by ``spec`` (or ``KEPLER_MODEL_BACKEND``).

    ``thinking_budget`` asks the provider to reveal its reasoning and bounds
    what it may spend on it. Only Anthropic takes a budget: the others either
    reveal reasoning without being asked or not at all, so the argument is
    accepted and ignored rather than made an error -- a caller should not have
    to know which provider it landed on to ask for the same thing.
    """

    spec = spec or os.environ.get("KEPLER_MODEL_BACKEND")
    if not spec:
        raise ValueError(
            "no backend spec given and KEPLER_MODEL_BACKEND is not set"
        )
    provider, model = parse_spec(spec)

    if provider == "anthropic":
        from tools.llm.anthropic_backend import AnthropicBackend

        return AnthropicBackend(
            model=model, api_key=api_key, thinking_budget=thinking_budget
        )

    if provider == "openai":
        return _build_openai(model, api_key, base_url, transport)

    if provider == "ollama":
        from tools.llm.ollama_backend import OllamaBackend

        # No api_key is ever passed to Ollama.
        return OllamaBackend(
            model=model,
            base_url=base_url or os.environ.get("OLLAMA_BASE_URL"),
            transport=transport,
        )

    if provider == "gemini":
        return _build_gemini(model, api_key, base_url, transport)

    raise ValueError(
        f"unknown provider {provider!r}; recognized: {', '.join(RECOGNIZED_PROVIDERS)}"
    )


def _build_openai(
    model: str, api_key: str | None, base_url: str | None, transport: Any
) -> ModelBackend:
    from tools.llm.openai_backend import OpenAIBackend

    resolved_base = base_url or os.environ.get("OPENAI_BASE_URL")
    on_default_host = (
        resolved_base is None
        or resolved_base.rstrip("/") == _OPENAI_DEFAULT_BASE_URL
    )

    if api_key is not None:
        resolved_key: str | None = api_key
    elif on_default_host:
        resolved_key = os.environ.get("OPENAI_API_KEY")
    else:
        # S3: an environment key never travels to a non-default host. Pairing
        # requires api_key= and base_url= to be supplied together.
        resolved_key = None

    return OpenAIBackend(
        model=model,
        base_url=resolved_base,
        api_key=resolved_key,
        transport=transport,
    )


def _build_gemini(
    model: str, api_key: str | None, base_url: str | None, transport: Any
) -> ModelBackend:
    from tools.llm.gemini_backend import GEMINI_DEFAULT_BASE_URL, GeminiBackend

    on_default_host = (
        base_url is None
        or base_url.rstrip("/") == GEMINI_DEFAULT_BASE_URL
    )
    if api_key is not None:
        resolved_key: str | None = api_key
    elif on_default_host:
        resolved_key = os.environ.get("GEMINI_API_KEY")
    else:
        # S3: an environment key never travels to a non-default host. Pairing
        # requires api_key= and base_url= to be supplied together.
        resolved_key = None

    return GeminiBackend(
        model=model,
        api_key=resolved_key,
        base_url=base_url,
        transport=transport,
    )
