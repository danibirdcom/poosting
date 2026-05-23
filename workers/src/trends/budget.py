"""Enforcement de presupuesto por (medio, servicio).

Cap mensual con threshold a 95%. La reserva es atómica: ``UPDATE ... WHERE
gasto + coste <= budget * 0.95 RETURNING`` — si la fila no se devuelve, el
budget no daba para esta llamada y abortamos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

# Umbral de soft-stop: si el reservar superaría este % del budget, abortamos.
UMBRAL_FRACCION = Decimal("0.95")


class BudgetExceededError(RuntimeError):
    """El budget mensual de (medio, servicio) está agotado o se superaría."""


@dataclass(frozen=True)
class BudgetReservation:
    presupuesto_id: UUID
    gasto_tras_reserva_eur: Decimal


def _mes_ref(now: datetime | None = None) -> date:
    n = now or datetime.now(tz=UTC)
    return date(n.year, n.month, 1)


async def reservar(
    conn: asyncpg.Connection,
    medio_id: UUID,
    servicio: str,
    coste_estimado_eur: Decimal,
    now: datetime | None = None,
) -> BudgetReservation:
    """Reserva ``coste_estimado_eur`` contra el budget de (medio, servicio).

    - Si no existe budget configurado para ese (medio, servicio, mes_ref),
      lanza ``BudgetExceededError`` (failsafe: sin budget explícito = no se gasta).
    - Si la reserva superaría el 95% del budget, lanza ``BudgetExceededError``.
    - En éxito, devuelve la reserva. NO requiere commit posterior: el caller
      debe estar dentro de su propia transacción.
    """
    mes = _mes_ref(now)

    row = await conn.fetchrow(
        """
        UPDATE presupuestos_api
           SET gasto_mes_actual_eur = gasto_mes_actual_eur + $1,
               actualizado_at = NOW()
         WHERE medio_id = $2
           AND servicio = $3
           AND mes_ref = $4
           AND (gasto_mes_actual_eur + $1) <= (budget_mensual_eur * $5)
         RETURNING id, gasto_mes_actual_eur
        """,
        coste_estimado_eur,
        medio_id,
        servicio,
        mes,
        UMBRAL_FRACCION,
    )
    if row is None:
        # Diferenciamos "no existe budget" vs "lo superaría". Útil para el log.
        existe = await conn.fetchval(
            "SELECT 1 FROM presupuestos_api WHERE medio_id=$1 AND servicio=$2 AND mes_ref=$3",
            medio_id,
            servicio,
            mes,
        )
        razon = "budget_no_configurado" if existe is None else "budget_excedido"
        logger.warning(
            "budget_reservar_fallido",
            medio_id=str(medio_id),
            servicio=servicio,
            mes=mes.isoformat(),
            coste_eur=str(coste_estimado_eur),
            razon=razon,
        )
        raise BudgetExceededError(f"{servicio}: {razon}")

    return BudgetReservation(
        presupuesto_id=row["id"],
        gasto_tras_reserva_eur=Decimal(str(row["gasto_mes_actual_eur"])),
    )


async def liberar(
    conn: asyncpg.Connection,
    presupuesto_id: UUID,
    importe_eur: Decimal,
) -> None:
    """Devuelve un importe reservado (p.ej. si la llamada falla antes de gastar).

    Se aplica con CHECK >= 0 a nivel BD, así que nunca dejamos el contador
    en negativo.
    """
    await conn.execute(
        "UPDATE presupuestos_api "
        "SET gasto_mes_actual_eur = GREATEST(0, gasto_mes_actual_eur - $1), "
        "    actualizado_at = NOW() "
        "WHERE id = $2",
        importe_eur,
        presupuesto_id,
    )
