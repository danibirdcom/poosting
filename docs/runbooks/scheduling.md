# Runbook: Scheduling del workflow `detect-signals`

## Estado actual (Fase 2, validación inicial)

**El cron está DESACTIVADO.** El workflow `.github/workflows/detect-signals.yml`
solo se dispara vía `workflow_dispatch` (botón "Run workflow" en la UI de
GitHub Actions o por API).

Razón: tras el merge del backend de Fase 2 (PR #2) acordamos un período
de 72h de validación manual antes de activar el cron `*/15`. Los runs
los dispara Dani 4-6 veces el primer día para verificar:
- Volumen real de señales por fuente.
- Gasto real de X API contra el budget de 25 €/mes.
- Feeds descubiertos / errores por feed.
- Que no hay regresiones tras los fixes (PR #3 codec JSONB, PR #4
  aislamiento + retries).

## Cómo reactivar el cron

Cuando hayan pasado las 72h sin incidencias:

1. Edita `.github/workflows/detect-signals.yml`.
2. Descomenta el bloque `schedule:` (las líneas con `# schedule:` y
   `#   - cron: "*/15 * * * *"`).
3. Considera bajar la frecuencia inicial a `*/30` si solo Hoy Aragón
   está onboardeado — los otros 2 medios del matrix son no-ops y
   consumen runner-minutes inútilmente.
4. PR + merge.

## Ejecutar manualmente

```bash
# Disparar el workflow para Hoy Aragón:
gh workflow run detect-signals.yml -f medio_slug=hoy-aragon

# Limitar a un detector concreto:
gh workflow run detect-signals.yml -f medio_slug=hoy-aragon -f detector=rss
```

O desde la UI: Actions → "Detect signals" → "Run workflow" → seleccionar
inputs.

## Cómo se verá cuando el cron esté activo

- Frecuencia inicial: `*/15` (cada 15 min) — 96 runs/día.
- Cada run dispara un matrix de 3 medios → 3 jobs por run.
- Coste GH Actions: ~5 min/job × 3 medios × 96 runs/día ≈ 24 horas-runner/día.
  Dentro del free tier de la mayoría de planes para repos públicos. Para
  privados, vigilar.
- Cuando provisionemos EC2/Coolify con BullMQ (Fase 3+), este workflow se
  desactiva del todo y queda solo como botón de pánico (`workflow_dispatch`).

## Histórico de decisiones

| Fecha | Decisión |
|---|---|
| 2026-05-22 | Cron */15 activo desde el merge inicial de Fase 2. |
| 2026-05-22 | Run #7 expuso bugs (codec JSONB + transacción global). Hotfix en PR #3 y PR #4. |
| 2026-05-23 | Tras los fixes, **desactivamos el cron** durante 72h para validación manual. Solo `workflow_dispatch`. |
| 2026-05-24 | Cron schedule reactivado tras validación manual exitosa. Fase 2 cerrada con 45 señales reales detectadas, hash de merge fase 2 = `e1f25da`. |
