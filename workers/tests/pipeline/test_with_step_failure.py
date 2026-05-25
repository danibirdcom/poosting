"""Tests del comportamiento de ``with_step`` ante excepciones (Bug E robustez).

Verifica que si el cuerpo del context manager lanza, ``with_step``:
  1. UPDATEa la fila con estado='fallido', error y finalizado_at.
  2. Re-lanza la excepción para que el grafo la vea.

Usa un fake de pool/conn (no toca BD real) para que el test corra sin
DATABASE_URL.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.pipeline.persistence import with_step


class _FakeConn:
    """Mínimo asyncpg.Connection — registra cada execute/fetchval."""

    def __init__(self, step_id: Any) -> None:
        self._step_id = step_id
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.execute_calls.append((sql, args))
        return "OK"

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.fetchval_calls.append((sql, args))
        # Solo el INSERT inicial usa fetchval para devolver el step_id.
        return self._step_id


class _FakePoolAcquireCM:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakePoolAcquireCM:
        return _FakePoolAcquireCM(self._conn)


def _ultimo_update_estado(conn: _FakeConn) -> str | None:
    """Devuelve el valor literal de ``SET estado = '...'`` del último UPDATE."""
    for sql, _args in reversed(conn.execute_calls):
        if "UPDATE run_steps" in sql:
            if "estado = 'fallido'" in sql:
                return "fallido"
            if "estado = 'completado'" in sql:
                return "completado"
    return None


async def test_with_step_marca_fallido_si_cuerpo_lanza() -> None:
    """Excepción dentro de ``async with with_step(...)`` debe:
    - persistir UPDATE con estado='fallido', error, finalizado_at.
    - re-lanzar la excepción.
    """
    conn = _FakeConn(step_id=uuid4())
    pool = _FakePool(conn)

    medio_id = uuid4()
    run_id = uuid4()

    with pytest.raises(RuntimeError, match="boom"):
        async with with_step(
            pool,  # type: ignore[arg-type]
            medio_id,
            run_id,
            "write",
            {"x": 1},
        ):
            raise RuntimeError("boom desde nodo")

    estado = _ultimo_update_estado(conn)
    assert estado == "fallido", f"esperado UPDATE estado='fallido', got {estado!r}"

    # El SQL del UPDATE debe incluir error y finalizado_at.
    update_calls = [
        (sql, args) for sql, args in conn.execute_calls if "UPDATE run_steps" in sql
    ]
    assert len(update_calls) == 1, "debe haber un único UPDATE (el de fallido)"
    sql, args = update_calls[0]
    assert "error = $7" in sql or "error = " in sql
    assert "finalizado_at = NOW()" in sql
    # El mensaje de error en el UPDATE debe contener el tipo y el msg.
    error_str = next((a for a in args if isinstance(a, str) and "boom" in a), None)
    assert error_str is not None, f"no se persistió el error con 'boom': {args}"
    assert "RuntimeError" in error_str


async def test_with_step_marca_completado_si_cuerpo_no_lanza() -> None:
    """Camino normal: estado='completado' al salir limpio."""
    conn = _FakeConn(step_id=uuid4())
    pool = _FakePool(conn)

    async with with_step(
        pool,  # type: ignore[arg-type]
        uuid4(),
        uuid4(),
        "detect",
        {"x": 1},
    ) as step:
        step.output = {"tema_final": "X"}

    assert _ultimo_update_estado(conn) == "completado"


async def test_with_step_insert_inicial_es_ejecutando() -> None:
    """El INSERT inicial pone estado='ejecutando'."""
    conn = _FakeConn(step_id=uuid4())
    pool = _FakePool(conn)

    async with with_step(
        pool,  # type: ignore[arg-type]
        uuid4(),
        uuid4(),
        "research",
        {},
    ):
        pass

    # fetchval del INSERT contiene 'ejecutando'.
    assert conn.fetchval_calls, "no se hizo INSERT inicial"
    insert_sql, _ = conn.fetchval_calls[0]
    assert "INSERT INTO run_steps" in insert_sql
    assert "'ejecutando'" in insert_sql


# ---------------------------------------------------------------------------
# Routing: nodos saltados por motivo_aborto no reciben fila run_steps
# ---------------------------------------------------------------------------
def test_route_after_detect_aborto_va_a_publish() -> None:
    """Con `detect_motivo_aborto` set, el grafo enruta directo a publish
    saltando research/write/review/enrich. LangGraph no invoca esos
    nodos → `_ejecutar_step` NO se llama → 0 filas en run_steps para
    ellos. Quedan limpios, no como 'pendiente'.
    """
    from src.pipeline.graph import _route_after_detect

    assert _route_after_detect({"detect_motivo_aborto": "senal_ya_cubierta"}) == "publish"
    assert _route_after_detect({}) == "research"


def test_route_after_research_aborto_va_a_publish() -> None:
    """Igual con research_motivo_aborto: saltan write/review/enrich."""
    from src.pipeline.graph import _route_after_research

    assert (
        _route_after_research({"research_motivo_aborto": "fuentes_insuficientes"})
        == "publish"
    )
    assert _route_after_research({}) == "write"
