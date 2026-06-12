"""LOCAL_LLM_BASE_URL points every candidate model at one local OpenAI-compatible
server (Ollama / vLLM), sending the bare model name through — how the eval runs on
local agentic models."""

from dmcp.llm import OpenRouterClient


def test_local_base_url_override(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
    c = OpenRouterClient(model="gemma4:12b")
    assert str(c._client.base_url).rstrip("/").endswith("11434/v1")
    assert c.model == "gemma4:12b"  # bare tag sent through, not a provider-prefixed id


def test_local_api_key_override(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "sk-test")
    c = OpenRouterClient(model="qwen3:14b")
    assert c._client.api_key == "sk-test"


def test_explicit_base_url_beats_env(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
    c = OpenRouterClient(model="x", base_url="http://other:8000/v1", api_key="k")
    assert "other:8000" in str(c._client.base_url)
