#!/usr/bin/env python
"""Carga db/seeds/blacklist_dominios.txt a la tabla `blacklist_dominios`.

Idempotente: usa ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import asyncpg
import asyncio

DSN = os.environ.get("DATABASE_URL", "postgresql://redactia:redactia@localhost:5432/redactia")
SEED = Path(__file__).resolve().parent.parent / "db" / "seeds" / "blacklist_dominios.txt"


async def main() -> int:
    if not SEED.exists():
        print(f"no existe {SEED}", file=sys.stderr)
        return 1

    entries: list[tuple[str, str]] = []
    for raw in SEED.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            print(f"línea ignorada (formato dominio|razón): {line}", file=sys.stderr)
            continue
        dominio, razon = line.split("|", 1)
        entries.append((dominio.strip().lower(), razon.strip()))

    conn = await asyncpg.connect(DSN)
    try:
        async with conn.transaction():
            await conn.executemany(
                "INSERT INTO blacklist_dominios (dominio, razon) "
                "VALUES ($1, $2) ON CONFLICT (dominio) DO UPDATE SET razon = EXCLUDED.razon",
                entries,
            )
        print(f"cargados {len(entries)} dominios en blacklist")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
