#!/usr/bin/env python
"""Onboarding del medio piloto 'Hoy Aragón'.

Crea (o reusa) el medio + perfiles de detección + fuentes_configuradas +
presupuesto X API. Idempotente: ON CONFLICT DO NOTHING / UPDATE.

Uso:
    DATABASE_URL_ADMIN=... python scripts/seed_hoy_aragon.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal

import asyncpg

DSN = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL")


PERFILES = [
    {
        "nombre": "politica_aragon",
        "descripcion": "Política autonómica y municipal de Aragón.",
        "categoria_destino": "politica_local",
        "keywords_obligatorias": ["aragón", "zaragoza", "huesca", "teruel", "DGA", "Azcón", "Chueca"],
        "keywords_negativas": ["publirreportaje", "patrocinado"],
        "fuentes": [
            {
                "detector": "rss",
                "origen_url": "https://www.aragondigital.es/rss/listado/",
                "cron_expr": "*/15 * * * *",
                "config": {"feeds": ["https://www.aragondigital.es/rss/listado/"]},
                "usar_solo_como_senal": False,
            },
            {
                "detector": "rss",
                "origen_url": "https://www.20minutos.es/rss/aragon/",
                "cron_expr": "*/15 * * * *",
                "config": {"feeds": ["https://www.20minutos.es/rss/aragon/"]},
                "usar_solo_como_senal": False,
            },
            {
                "detector": "rss",
                "origen_url": "https://www.europapress.es/rss/rss.aspx?ch=00309",
                "cron_expr": "*/15 * * * *",
                "config": {"feeds": ["https://www.europapress.es/rss/rss.aspx?ch=00309"]},
                "usar_solo_como_senal": False,
            },
            {
                "detector": "rss",
                "origen_url": "https://www.heraldo.es/rss/",
                "cron_expr": "*/15 * * * *",
                "config": {"feeds": ["https://www.heraldo.es/rss/"]},
                "usar_solo_como_senal": True,
            },
            {
                "detector": "rss",
                "origen_url": "https://www.elperiodicodearagon.com/rss/",
                "cron_expr": "*/15 * * * *",
                "config": {"feeds": ["https://www.elperiodicodearagon.com/rss/"]},
                "usar_solo_como_senal": True,
            },
            {
                # Google News RSS — Google trata "gnews" como un feed RSS más,
                # no detector separado. Ver docs/agents/trend_detector.md
                # §"Decisión: gnews como fuente RSS".
                "detector": "rss",
                "origen_url": (
                    "https://news.google.com/rss/search"
                    "?q=Arag%C3%B3n+pol%C3%ADtica+OR+Az%C3%B3n+OR+DGA"
                    "&hl=es&gl=ES&ceid=ES:es"
                ),
                "cron_expr": "*/15 * * * *",
                "config": {
                    "feeds": [
                        "https://news.google.com/rss/search"
                        "?q=Arag%C3%B3n+pol%C3%ADtica+OR+Az%C3%B3n+OR+DGA"
                        "&hl=es&gl=ES&ceid=ES:es"
                    ]
                },
                "usar_solo_como_senal": False,
            },
            {
                "detector": "gtrends",
                "origen_url": None,
                "cron_expr": "*/30 * * * *",
                "config": {
                    "geos": [{"geo": "ES-AR", "peso": 0.7}, {"geo": "ES", "peso": 0.3}],
                    "max_resultados": 20,
                },
                "usar_solo_como_senal": False,
            },
            {
                "detector": "gdelt",
                "origen_url": None,
                "cron_expr": "0 * * * *",
                "config": {"max_records": 50, "timespan": "24h"},
                "usar_solo_como_senal": False,
            },
            {
                "detector": "x",
                "origen_url": None,
                "cron_expr": "0 */2 * * *",   # cada 2h, conservador para budget
                "config": {"max_results": 15},
                "usar_solo_como_senal": False,
            },
        ],
    },
]


async def main() -> int:
    if not DSN:
        print("ERROR: define DATABASE_URL_ADMIN o DATABASE_URL", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(DSN)
    try:
        async with conn.transaction():
            medio_id = await conn.fetchval(
                """
                INSERT INTO medios (slug, nombre, cms_tipo, cms_config)
                VALUES ('hoy-aragon', 'Hoy Aragón', 'wordpress', '{}'::jsonb)
                ON CONFLICT (slug) DO UPDATE SET nombre = EXCLUDED.nombre
                RETURNING id
                """,
            )
            print(f"medio Hoy Aragón: {medio_id}")

            # A partir de aquí toda inserción va a tablas con RLS+FORCE, así que
            # fijamos el contexto multi-tenant. Sin esto, el owner también es
            # bloqueado por las policies (WITH CHECK medio_id = app_current_medio()).
            await conn.execute("SELECT set_config('app.medio_actual', $1, true)", str(medio_id))

            # scoring_pesos defaults por categoría
            await conn.execute(
                """
                INSERT INTO scoring_pesos (medio_id, categoria, peso_velocidad,
                  peso_volumen, peso_freshness, peso_intent)
                VALUES ($1, 'politica_local', 1.0, 1.0, 1.5, 1.0)
                ON CONFLICT (medio_id, categoria) DO NOTHING
                """,
                medio_id,
            )

            # presupuesto X API: 25 €/mes
            mes_ref = date(datetime.now(tz=UTC).year, datetime.now(tz=UTC).month, 1)
            await conn.execute(
                """
                INSERT INTO presupuestos_api (medio_id, servicio, budget_mensual_eur, mes_ref)
                VALUES ($1, 'x_api', $2, $3)
                ON CONFLICT (medio_id, servicio, mes_ref) DO NOTHING
                """,
                medio_id,
                Decimal("25.00"),
                mes_ref,
            )

            for p in PERFILES:
                perfil_id = await conn.fetchval(
                    """
                    INSERT INTO perfiles_deteccion (
                      medio_id, nombre, descripcion, categoria_destino,
                      keywords_obligatorias, keywords_negativas
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (medio_id, nombre) DO UPDATE
                       SET descripcion = EXCLUDED.descripcion,
                           keywords_obligatorias = EXCLUDED.keywords_obligatorias,
                           keywords_negativas = EXCLUDED.keywords_negativas
                    RETURNING id
                    """,
                    medio_id,
                    p["nombre"],
                    p["descripcion"],
                    p["categoria_destino"],
                    p["keywords_obligatorias"],
                    p["keywords_negativas"],
                )
                print(f"  perfil {p['nombre']}: {perfil_id}")

                # Upsert por clave natural (perfil_id, detector, origen_url).
                # Conserva el UUID y ultima_ejec_at de fuentes ya existentes.
                # Re-ejecutar añade SOLO las nuevas. Si quieres modificar
                # cron_expr o config de una existente, edita en BD a mano.
                insertadas = 0
                for f in p["fuentes"]:
                    ya_existe = await conn.fetchval(
                        """
                        SELECT 1 FROM fuentes_configuradas
                         WHERE perfil_id = $1
                           AND detector = $2
                           AND origen_url IS NOT DISTINCT FROM $3
                        """,
                        perfil_id,
                        f["detector"],
                        f["origen_url"],
                    )
                    if ya_existe:
                        continue
                    await conn.execute(
                        """
                        INSERT INTO fuentes_configuradas (
                          medio_id, perfil_id, detector, origen_url, cron_expr,
                          config, usar_solo_como_senal
                        )
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                        """,
                        medio_id,
                        perfil_id,
                        f["detector"],
                        f["origen_url"],
                        f["cron_expr"],
                        json.dumps(f["config"]),
                        f["usar_solo_como_senal"],
                    )
                    insertadas += 1
                print(f"  fuentes nuevas: {insertadas} (definidas: {len(p['fuentes'])})")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
