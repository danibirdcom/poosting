#!/usr/bin/env python
"""Marca todas las ``fuentes_configuradas`` con ``detector='gtrends'`` como
``activo=FALSE``.

Razón: el endpoint público ``https://trends.google.com/trends/api/dailytrends``
devuelve 404 persistentemente (verificado run #17 con UA realista y geo=ES).
Hasta investigar el reemplazo, mejor que el cron no las intente y consuma
ciclos.

El código del detector ``gtrends.py`` se queda en su sitio. Cuando el
sustituto esté listo (issue Fase 2.5: "Reemplazar GTrends por SerpAPI Trends
o pytrends actualizado"), basta un ``UPDATE ... SET activo = TRUE`` manual
o reseed.

Uso:
    DATABASE_URL_ADMIN=<dsn admin> python scripts/desactivar_gtrends.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

DSN = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL")


async def main() -> int:
    if not DSN:
        print(
            "ERROR: define DATABASE_URL_ADMIN o DATABASE_URL en el entorno",
            file=sys.stderr,
        )
        return 1

    conn = await asyncpg.connect(DSN)
    try:
        # Iteramos por medio porque FORCE RLS en fuentes_configuradas exige
        # app.medio_actual fijo. Si el admin de tu RDS tiene BYPASSRLS,
        # podrías hacer un UPDATE único — pero el loop es portable.
        medios = await conn.fetch("SELECT id, slug FROM medios WHERE activo = TRUE")
        total = 0
        for m in medios:
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(m["id"])
            )
            result = await conn.execute(
                "UPDATE fuentes_configuradas "
                "   SET activo = FALSE "
                " WHERE detector = 'gtrends' AND activo = TRUE"
            )
            # result tipo "UPDATE N"
            n = int(result.split()[-1])
            total += n
            if n > 0:
                print(f"  {m['slug']}: {n} fuente(s) gtrends desactivada(s)")
        print(f"Total: {total} fuente(s) gtrends desactivada(s) en {len(medios)} medio(s)")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
