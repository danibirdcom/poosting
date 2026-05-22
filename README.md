# Redactia

Plataforma multi-tenant para automatización editorial. Detecta tendencias,
investiga fuentes, redacta artículos imitando el estilo de redactores reales,
y publica en el CMS del medio con feedback de GSC.

> Lee `CLAUDE.md` para la spec completa de arquitectura, stack y políticas.

## Quick start (dev)

Requisitos: Docker, Docker Compose, `uv` (Python), `pnpm` (Node 20+).

```bash
cp .env.example .env
# editar .env con tus claves de APIs

docker compose up -d postgres redis minio
make db-migrate
make db-seed

# API
cd api && uv sync && uv run uvicorn src.main:app --reload

# Workers (en otra terminal)
cd workers && uv sync && uv run python -m src.main

# Dashboard (en otra terminal)
cd dashboard && pnpm install && pnpm dev
```

## Estructura

Ver árbol de carpetas en `CLAUDE.md` §8.

## Fase actual

Bootstrap (Fase 1-2). Ver `docs/plan.md`.
