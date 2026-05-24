"""Tests del cliente ClaudeReal — mock del SDK Anthropic vía monkeypatch.

Validamos:
- Tracking de tokens por modelo.
- Helper ``json_output_kwargs`` produce prefill='{' y system con JSON-only.
- Sin API key → RuntimeError en construcción.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.llm.claude import ClaudeReal, json_output_kwargs


@dataclass
class FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class FakeContentBlock:
    text: str
    type: str = "text"


@dataclass
class FakeMessage:
    content: list[FakeContentBlock]
    usage: FakeUsage


class FakeMessagesAPI:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.respuestas: list[FakeMessage] = []

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if not self.respuestas:
            return FakeMessage(
                content=[FakeContentBlock(text='"hola"')],
                usage=FakeUsage(input_tokens=10, output_tokens=2),
            )
        return self.respuestas.pop(0)


class FakeAsyncAnthropic:
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.messages = FakeMessagesAPI()


def _patch_anthropic(monkeypatch: pytest.MonkeyPatch) -> FakeAsyncAnthropic:
    """Sustituye anthropic.AsyncAnthropic por nuestro fake."""
    fake = FakeAsyncAnthropic()
    import src.llm.claude as mod

    monkeypatch.setattr(mod.anthropic, "AsyncAnthropic", lambda *a, **k: fake)
    return fake


async def test_claude_acumula_tokens_por_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_anthropic(monkeypatch)
    fake.messages.respuestas = [
        FakeMessage([FakeContentBlock("respuesta 1")], FakeUsage(100, 20)),
        FakeMessage([FakeContentBlock("respuesta 2")], FakeUsage(50, 10)),
    ]
    client = ClaudeReal(api_key="test-key")

    await client.generar("prompt 1", modelo="claude-sonnet-4-6")
    await client.generar("prompt 2", modelo="claude-haiku-4-5-20251001")

    assert client.calls_total == 2
    assert client.tokens_in_total == 150
    assert client.tokens_out_total == 30
    assert client.tokens_in_por_modelo == {
        "claude-sonnet-4-6": 100,
        "claude-haiku-4-5-20251001": 50,
    }
    assert client.tokens_out_por_modelo == {
        "claude-sonnet-4-6": 20,
        "claude-haiku-4-5-20251001": 10,
    }


async def test_claude_prefill_se_prepende_a_la_respuesta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _patch_anthropic(monkeypatch)
    # Sin prefill, el cliente solo devuelve el texto del modelo.
    fake.messages.respuestas = [
        FakeMessage([FakeContentBlock('"k": "v"}')], FakeUsage(5, 5)),
    ]
    client = ClaudeReal(api_key="test-key")

    out = await client.generar("dame JSON", modelo="claude-haiku-4-5-20251001", prefill="{")
    assert out == '{"k": "v"}'
    # El prefill aparece en la llamada al SDK como un assistant message.
    last_call = fake.messages.calls[-1]
    messages = last_call["messages"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "{"


async def test_claude_pasa_system_y_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_anthropic(monkeypatch)
    fake.messages.respuestas = [
        FakeMessage([FakeContentBlock("ok")], FakeUsage(1, 1)),
    ]
    client = ClaudeReal(api_key="test-key")

    await client.generar(
        "prompt",
        modelo="claude-sonnet-4-6",
        system="Eres un editor.",
        temperature=0.1,
    )
    last_call = fake.messages.calls[-1]
    assert last_call["system"] == "Eres un editor."
    assert last_call["temperature"] == 0.1


def test_claude_sin_api_key_lanza() -> None:
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ClaudeReal(api_key="")


def test_json_output_kwargs_estructura() -> None:
    kw = json_output_kwargs()
    assert kw["prefill"] == "{"
    assert kw["temperature"] == 0.3
    assert "JSON" in kw["system"]
    assert "markdown" in kw["system"]

    kw2 = json_output_kwargs(extra_system="Sé conciso.")
    assert "Sé conciso." in kw2["system"]
    assert "JSON" in kw2["system"]
