"""``parse_spec`` and ``build_backend`` -- spec parsing and the S3 credential/
endpoint binding rule.

Phase 2a of docs/working/model-backends.md, sections 4.3 and S3.
"""

from __future__ import annotations

import pytest

from tests.llm_fakes import CapturingTransport, openai_chat_response
from tools.llm import base
from tools.llm.factory import build_backend, parse_spec


# --- parse_spec: first slash only -----------------------------------


def test_spec_splits_on_the_first_slash_only():
    assert parse_spec("ollama/llama3.1:8b") == ("ollama", "llama3.1:8b")
    assert parse_spec("anthropic/claude-opus-5") == ("anthropic", "claude-opus-5")
    assert parse_spec("openai/meta-llama/Llama-3-8b") == (
        "openai",
        "meta-llama/Llama-3-8b",
    )


def test_spec_without_a_slash_is_rejected():
    with pytest.raises(ValueError):
        parse_spec("gpt-4.1")


def test_an_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        build_backend("mystery/model")


# --- resolution order ----------------------------------------------


def test_the_spec_argument_beats_KEPLER_MODEL_BACKEND(monkeypatch):
    monkeypatch.setenv("KEPLER_MODEL_BACKEND", "anthropic/claude-sonnet-5")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    backend = build_backend("openai/gpt-4.1", transport=CapturingTransport()())
    assert backend.spec == "openai/gpt-4.1"


def test_no_spec_and_no_env_is_an_error(monkeypatch):
    monkeypatch.delenv("KEPLER_MODEL_BACKEND", raising=False)
    with pytest.raises(ValueError):
        build_backend()


def test_missing_openai_key_on_the_default_host_raises_backend_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(base.BackendUnavailableError) as excinfo:
        build_backend("openai/gpt-4.1")
    assert excinfo.value.variable == "OPENAI_API_KEY"


# --- S3: credential is bound to endpoint -------------------------


def _auth_header(backend) -> str | None:
    capture = CapturingTransport(openai_chat_response())
    backend._transport = capture()  # swap in a recording transport
    backend.complete(messages=(), tools=[], system="s", max_tokens=16)
    return capture.last.headers.get("authorization")


def test_env_key_reaches_the_default_host():
    from tools.llm.openai_backend import OpenAIBackend

    backend = OpenAIBackend(model="gpt-4.1", api_key="sk-default-paired")
    assert _auth_header(backend) == "Bearer sk-default-paired"


def test_env_key_is_not_sent_to_a_non_default_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-travel")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    backend = build_backend(
        "openai/gpt-4.1",
        base_url="https://proxy.example.com/v1",
        transport=CapturingTransport(openai_chat_response())(),
    )
    assert _auth_header(backend) is None


def test_OPENAI_BASE_URL_in_the_environment_does_not_pair_the_env_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-travel")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example.com/v1")
    backend = build_backend("openai/gpt-4.1")
    assert _auth_header(backend) is None


def test_an_explicitly_paired_key_travels_to_a_non_default_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = build_backend(
        "openai/gpt-4.1",
        base_url="https://proxy.example.com/v1",
        api_key="sk-explicitly-paired",
    )
    assert _auth_header(backend) == "Bearer sk-explicitly-paired"


def test_no_auth_header_over_plaintext_http_to_a_non_loopback_host():
    from tools.llm.openai_backend import OpenAIBackend

    backend = OpenAIBackend(
        model="gpt-4.1", base_url="http://insecure.example.com/v1", api_key="sk-x"
    )
    assert _auth_header(backend) is None


def test_auth_header_is_allowed_over_plaintext_http_to_loopback():
    from tools.llm.openai_backend import OpenAIBackend

    backend = OpenAIBackend(
        model="local", base_url="http://127.0.0.1:8000/v1", api_key="sk-local"
    )
    assert _auth_header(backend) == "Bearer sk-local"


# --- S3 transport hardening --------------------------------------


def test_the_http_client_never_follows_redirects_and_always_has_a_timeout():
    from tools.llm.openai_backend import OpenAIBackend

    backend = OpenAIBackend(model="gpt-4.1", api_key="sk-x")
    client = backend._client()
    try:
        assert client.follow_redirects is False
        assert client.timeout.read is not None
    finally:
        client.close()


# --- S4: no credential in any URL --------------------------------


def test_no_credential_appears_in_the_request_url():
    from tools.llm.openai_backend import OpenAIBackend

    capture = CapturingTransport(openai_chat_response())
    backend = OpenAIBackend(model="gpt-4.1", api_key="sk-secret", transport=capture())
    backend.complete(messages=(), tools=[], system="s", max_tokens=16)
    assert "sk-secret" not in str(capture.last.url)
