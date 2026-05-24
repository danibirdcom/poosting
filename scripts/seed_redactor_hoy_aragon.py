#!/usr/bin/env python
"""Onboarding del redactor virtual de Hoy Aragón para Fase 3.

Crea (idempotente):
- 1 ``redactor`` con ``nombre_publico = 'Redacción Hoy Aragón'``.
- 1 ``estilo_redactor`` v1 con un style guide default y ``activo=TRUE``.
- 0 ``ejemplos_redactor`` — Dani los importa por separado cuando recopile
  los reales.

Uso:
    DATABASE_URL_ADMIN=<dsn admin> python scripts/seed_redactor_hoy_aragon.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import asyncpg

DSN = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL")

NOMBRE_REDACTOR = "Redacción Hoy Aragón"

STYLE_GUIDE_DEFAULT = """# Guía de estilo — Redacción Hoy Aragón
Medio: hoy-aragon
Versión: 1 (default genérico)
Generada: 2026-05-24

## 1. Voz e identidad
- Tono: cercano pero riguroso, sin coloquialismos vacíos.
- Persona narrativa: 3ª persona impersonal por defecto.
- Registro: semiformal.
- Postura editorial: no opina, expone hechos verificados.

## 2. Estructura del artículo
- Apertura: dato concreto en el primer párrafo, contexto en el segundo.
- Longitud media: 700 palabras.
- H2 cada 3-4 párrafos.
- Cierre: resumen breve o dato que enmarca lo siguiente que ocurrirá.

## 3. Sintaxis
- Frase media: 18-25 palabras. Evitar frases > 35 salvo justificación.
- Párrafo medio: 3-4 frases.
- Voz pasiva: < 15% del total.

## 4. Vocabulario
- Palabras evitadas: "polémico", "histórico" (salvo que lo sea), "icónico".
- Anglicismos: solo si no hay equivalente en castellano de uso común.
- Tecnicismos: con glosa entre paréntesis la primera vez.

## 5. Convenciones de formato
- Comillas tipográficas «».
- Cifras: hasta nueve en letra; diez en adelante en cifra.
- Cargos en minúscula salvo al inicio de frase.
- Topónimos: forma oficial (Zaragoza, no Saraqusta).

## 6. Manejo de fuentes y citas
- Cita textual máxima: 15 palabras.
- Máximo una cita textual por fuente.
- Atribución: "según fuentes del Gobierno de Aragón" / "según el club".

## 7. Lo que NO hace este redactor
- Exclamaciones en titular.
- Preguntas retóricas como gancho.
- Mencionar redes sociales en titular.

> **Nota:** esta guía es un DEFAULT inicial. Será sustituida por una guía
> generada a partir de ejemplos reales del redactor cuando los importemos
> (Fase 4 o antes si Dani los provee).
"""

METRICAS_DEFAULT = {
    "longitud_media_frase_palabras": 22,
    "longitud_media_parrafo_frases": 3.5,
    "ratio_voz_pasiva": 0.10,
    "generado_desde": "default_genérico_sin_corpus",
}


async def main() -> int:
    if not DSN:
        print("ERROR: define DATABASE_URL_ADMIN o DATABASE_URL", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(DSN)
    # Codec JSONB para pasar dict directamente.
    for jsontype in ("jsonb", "json"):
        await conn.set_type_codec(
            jsontype,
            encoder=lambda v: v if isinstance(v, str) else json.dumps(v, default=str),
            decoder=json.loads,
            schema="pg_catalog",
        )
    try:
        async with conn.transaction():
            medio_id = await conn.fetchval(
                "SELECT id FROM medios WHERE slug = 'hoy-aragon' AND activo = TRUE"
            )
            if medio_id is None:
                print(
                    "ERROR: medio 'hoy-aragon' no existe. "
                    "Corre primero scripts/seed_hoy_aragon.py.",
                    file=sys.stderr,
                )
                return 2
            await conn.execute(
                "SELECT set_config('app.medio_actual', $1, false)", str(medio_id)
            )

            # Redactor (idempotente por nombre_publico dentro del medio)
            redactor_id = await conn.fetchval(
                "SELECT id FROM redactores "
                "WHERE medio_id = $1 AND nombre_publico = $2",
                medio_id,
                NOMBRE_REDACTOR,
            )
            if redactor_id is None:
                redactor_id = await conn.fetchval(
                    "INSERT INTO redactores (medio_id, nombre_publico) "
                    "VALUES ($1, $2) RETURNING id",
                    medio_id,
                    NOMBRE_REDACTOR,
                )
                print(f"  redactor creado: {redactor_id}")
            else:
                print(f"  redactor ya existía: {redactor_id}")

            # Estilo v1 activo (idempotente por redactor_id + version)
            existe_v1 = await conn.fetchval(
                "SELECT id FROM estilos_redactor "
                "WHERE redactor_id = $1 AND version = 1",
                redactor_id,
            )
            if existe_v1 is None:
                estilo_id = await conn.fetchval(
                    """
                    INSERT INTO estilos_redactor (
                      redactor_id, medio_id, version, guia_estilo_md,
                      metricas, activo
                    )
                    VALUES ($1, $2, 1, $3, $4, TRUE)
                    RETURNING id
                    """,
                    redactor_id,
                    medio_id,
                    STYLE_GUIDE_DEFAULT,
                    METRICAS_DEFAULT,
                )
                print(f"  estilo v1 creado: {estilo_id}")
            else:
                print(f"  estilo v1 ya existía: {existe_v1}")
    finally:
        await conn.close()
    print("\nSeed completado. Redactor listo para que el CLI redactar lo use.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
