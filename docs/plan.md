# Roadmap de Redactia

Este documento define las fases del desarrollo y sus criterios de aceptación.
Lectura obligatoria al inicio de cada sesión grande de trabajo.

## Fase 1 — Cimientos (semana 1-2) ✅ CERRADA

**Mergeada:** 2026-05-22 en `75229e3` (PR #1).

**Objetivo:** un entorno reproducible con BD, auth y multi-tenant funcionando.

**Entregables:**
- [x] Estructura de carpetas (CLAUDE.md §8).
- [x] `docker-compose.yml` con postgres + redis + minio.
- [x] Migración `001_initial.sql` con todas las tablas de §4 y RLS activado.
- [x] Skeleton de la API (FastAPI) con:
  - [x] Login + JWT
  - [x] Resolución de tenant por header `X-Medio-Id`
  - [x] CRUD de redactores como ejemplo de RLS-aware
- [x] Seeds: entidades Aragón + blacklist de dominios.
- [x] Test de RLS aislando dos medios (USING + WITH CHECK + sin contexto).
- [x] CI con RDS real (lint + tests). Workflow en `.github/workflows/ci.yml`.
- [x] Migración 002 con rol grupo `redactia_app` y grants explícitos.

**Criterios de aceptación:**
- `docker compose up -d` + `make db-migrate` + `make db-seed` deja la BD lista.
- `make api` arranca el API en `localhost:8000`.
- `POST /auth/login` devuelve token + lista de medios.
- `GET /redactores` con `X-Medio-Id` solo devuelve los del medio activo.
- Test `test_rls_aisla_redactores_entre_medios` pasa contra postgres real.

## Fase 2 — Trend detector + dashboard de señales (semana 3)

**Objetivo:** detectar tendencias y mostrarlas en UI.

**Entregables:**
- Workers de scraping para Google Trends, X (tier básico), GDELT, RSS de
  fuentes de cada medio.
- Tabla `senales` poblada con cron BullMQ (cada 15 min).
- Scoring compuesto (`scoring_pesos`) configurable por medio y categoría.
- Vista de bandeja de señales en el dashboard con filtros y "lanzar artículo".

**Criterios de aceptación:**
- Cada origen escribe al menos 50 señales/día en dev.
- Score reproducible: misma señal mismos parámetros → mismo score.
- Dashboard muestra top 50 ordenadas por score con metadata.
- Click en señal → modal con "asignar a redactor X y lanzar pipeline".

## Fase 3 — Pipeline multiagente básico (semana 4-5)

**Objetivo:** generar un artículo end-to-end sin estilo personalizado todavía.

**Entregables:**
- LangGraph con nodos: `detect → research → write → review → enrich → publish`.
- Persistencia de `runs` y `run_steps`.
- Mocks de `publish` (sin CMS real todavía, deja en `bandeja`).
- Vista "Bandeja editorial" en dashboard para aprobar/rechazar.

**Criterios de aceptación:**
- Run manual desde dashboard genera draft completo en < 90 s.
- Cada step grabado con prompt, modelo y tokens.
- Re-ejecutar un run desde un step intermedio funciona (idempotencia).
- Test e2e con LLM mockeado pasa.

## Fase 4 — Style profile por redactor (semana 6)

**Objetivo:** personalizar la voz por redactor real del medio.

**Entregables:**
- UI para pegar 10-30 ejemplos de un redactor.
- `style_profile/builder.py`: genera guía de estilo + métricas a partir de ejemplos.
- `correcciones_redactor` capturadas desde el editor (Tiptap diff).
- `updater.py`: regenera versión de estilo cuando hay 20+ correcciones nuevas.

**Criterios de aceptación:**
- Artículos generados con `estilo_id` activo se parecen significativamente al
  redactor (validación humana en backoffice).
- Cada nueva versión del estilo incrementa `version` y se guarda histórico.

## Fase 5 — CMS adapters (semana 7)

**Objetivo:** publicar de verdad en WordPress y OpenHost/OpenDemas.

**Entregables:**
- Interfaz abstracta `CMSAdapter` con `publish/update/delete/get_categories/get_tags/upload_media`.
- Adapter WordPress (REST API + Application Passwords).
- Adapter OpenDemas (a definir según docs).
- Tests con mock + staging real.

**Criterios de aceptación:**
- Publicar un draft de Hoy Aragón llega al WordPress de staging con imagen,
  tags, categorías y schema JSON-LD correctos.
- Modo `borrador_cms` deja el post como draft visible en el CMS nativo.

## Fase 6 — SEO/Discover (semana 8)

**Objetivo:** enriquecimiento profesional del artículo.

**Entregables:**
- Entidades del catálogo enlazadas al CMS (creación de tags).
- Internal linking con vector search.
- JSON-LD NewsArticle completo.
- Open Graph + Twitter cards.
- Meta title distinto del H1, slug optimizado.

## Fase 7 — Automatizaciones + bandeja editorial (semana 9)

**Objetivo:** funcionamiento desatendido.

**Entregables:**
- CRUD de automatizaciones (cron + config).
- Scheduler con BullMQ que lanza pipelines.
- Bandeja editorial completa con filtros, búsqueda, edición Tiptap.
- Modos: auto, borrador_cms, bandeja, programado.

## Fase 8 — Feedback loop GSC (semana 10)

**Objetivo:** ajustar el scoring con datos reales de tráfico.

**Entregables:**
- OAuth de Google Search Console por medio.
- Worker que captura métricas a 24h/72h/7d/30d tras publicar.
- Algoritmo de ajuste de `scoring_pesos` por categoría.
- Vista de métricas en dashboard.

## Fase 9+ — Evergreen, live blog, multi-medio onboarding

A definir cuando lleguemos.

---

## Convenciones del roadmap

- Cada fase se cierra con un demo grabado y un PR final.
- Los criterios de aceptación se verifican antes de mover el checkbox.
- Si una fase desborda en tiempo, decidimos: extender vs. trocear.
- Cambios de arquitectura entre fases requieren PR a `CLAUDE.md` antes.
