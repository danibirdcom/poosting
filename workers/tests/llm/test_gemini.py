"""Tests del cliente GeminiReal con grounding.

Mock del SDK google-genai vía monkeypatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.llm.gemini import GeminiReal


@dataclass
class FakeUsageMeta:
    prompt_token_count: int
    candidates_token_count: int


@dataclass
class FakeGroundingWeb:
    uri: str
    title: str


@dataclass
class FakeGroundingChunk:
    web: FakeGroundingWeb


@dataclass
class FakeGroundingMeta:
    grounding_chunks: list[FakeGroundingChunk] = field(default_factory=list)


@dataclass
class FakeCandidate:
    grounding_metadata: FakeGroundingMeta | None = None


@dataclass
class FakeResp:
    text: str
    usage_metadata: FakeUsageMeta
    candidates: list[FakeCandidate] = field(default_factory=list)


class FakeModelsAPI:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.respuestas: list[FakeResp] = []

    async def generate_content(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if not self.respuestas:
            return FakeResp(text="ok", usage_metadata=FakeUsageMeta(10, 5))
        return self.respuestas.pop(0)


class FakeAio:
    def __init__(self) -> None:
        self.models = FakeModelsAPI()


class FakeGeminiClient:
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.aio = FakeAio()


def _patch_gemini(monkeypatch: pytest.MonkeyPatch) -> FakeGeminiClient:
    fake = FakeGeminiClient()
    import src.llm.gemini as mod

    monkeypatch.setattr(mod.genai, "Client", lambda *a, **k: fake)
    return fake


async def test_gemini_tracking_basico(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_gemini(monkeypatch)
    fake.aio.models.respuestas = [
        FakeResp(text="hola", usage_metadata=FakeUsageMeta(100, 50)),
    ]
    client = GeminiReal(api_key="test-key")

    out = await client.generar("prompt", modelo="gemini-2.5-flash")
    assert out == "hola"
    assert client.tokens_in_total == 100
    assert client.tokens_out_total == 50
    assert client.calls_total == 1
    assert client.tokens_in_por_modelo["gemini-2.5-flash"] == 100


async def test_gemini_grounding_activa_tool_google_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _patch_gemini(monkeypatch)
    fake.aio.models.respuestas = [
        FakeResp(
            text="con citas",
            usage_metadata=FakeUsageMeta(50, 30),
            candidates=[
                FakeCandidate(
                    grounding_metadata=FakeGroundingMeta(
                        grounding_chunks=[
                            FakeGroundingChunk(
                                FakeGroundingWeb("https://aragondigital.es/x", "AD")
                            ),
                            FakeGroundingChunk(
                                FakeGroundingWeb("https://europapress.es/y", "EP")
                            ),
                        ]
                    )
                ),
            ],
        ),
    ]
    client = GeminiReal(api_key="test-key")

    out = await client.generar(
        "sintetiza hechos", modelo="gemini-2.5-flash", grounding=True
    )
    assert out == "con citas"
    # Verifica que se pasó tools con google_search
    last_call = fake.aio.models.calls[-1]
    config = last_call["config"]
    assert config.tools is not None
    # google_search es el atributo dentro del Tool genai_types
    assert config.tools[0].google_search is not None
    # Citas extraídas y agregadas
    assert len(client.citas_grounding) == 2
    assert client.citas_grounding[0]["url"] == "https://aragondigital.es/x"


async def test_gemini_sin_grounding_no_pasa_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _patch_gemini(monkeypatch)
    fake.aio.models.respuestas = [
        FakeResp(text="ok", usage_metadata=FakeUsageMeta(1, 1)),
    ]
    client = GeminiReal(api_key="test-key")

    await client.generar("p", modelo="gemini-2.5-flash")
    last_call = fake.aio.models.calls[-1]
    config = last_call["config"]
    assert config.tools is None


def test_gemini_sin_api_key_lanza() -> None:
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiReal(api_key="")
