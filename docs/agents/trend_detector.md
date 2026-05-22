# Detector de tendencias (Fase 2)

> Componente que pobla la tabla `senales` con candidatos a tema editorial.
> No decide qué se escribe (eso es del nodo `detect` del pipeline en Fase 3).

## Diseño

### Pipeline por ejecución de fuente

```
fuente_configurada (BD)
        │
        ▼
DetectorContext  ──►  TrendDetector.detectar()  ──►  [SenalCruda]
                                                          │
                                                          ▼
                                              embeddings (Voyage)
                                                          │
                                  ┌───────────────────────┴────────┐
                                  ▼                                ▼
                            dedupe.buscar_similar          (no match)
                              (cosine > 0.85)                      │
                                  │                                ▼
                                  ▼                       scorer.score_compuesto
                       dedupe.actualizar_similar                   │
                                                                   ▼
                                                            insertar_senal
```

### Detectores incluidos

| Detector | Estado | Notas |
|---|---|---|
| **RSS** (`rss.py`) | Funcional | Parser propio (sin feedparser para reducir deps). RSS 2.0 + Atom. Tolerante a feeds rotos. |
| **Google Trends** (`gtrends.py`) | Funcional | Endpoint público sin clave. Mezcla configurable de geos con pesos (ES-AR vs ES). |
| **GDELT** (`gdelt.py`) | Funcional | DOC API v2. Sin clave, rate limits razonables. |
| **X API** (`x_api.py`) | Funcional con budget hard-cap | Necesita `X_API_BEARER` + entrada en `presupuestos_api`. Sin bearer hace skip silencioso. |

### Decisión: dedupe semántico vs clustering

**Decisión:** dedupe simple por cosine similarity (umbral 0.85) en una
ventana de 24 horas. No usamos HDBSCAN ni clustering jerárquico en Fase 2.

**Razonamiento:**

1. **Simple es testeable.** `buscar_similar` es una query con índice HNSW,
   determinista para un mismo embedding. HDBSCAN tiene hiperparámetros
   (`min_cluster_size`, `min_samples`, `cluster_selection_epsilon`) que en
   un dataset pequeño y heterogéneo dan resultados inestables entre runs.
   Para el dashboard "top 50 señales" eso es ruido.

2. **No tenemos suficiente densidad todavía.** En Fase 2 estamos en el
   orden de centenares de señales/día por medio. Clustering brilla cuando
   tienes miles de puntos con estructura clara. Antes, da clusters de 1-2.

3. **La unidad de trabajo del usuario es la señal, no el cluster.** En el
   dashboard, el editor decide "lanzo artículo sobre esta señal". No
   "lanzo artículo sobre este cluster". Si dos señales del mismo evento
   llegan a la lista, ya las habremos fusionado vía dedupe; si no, son
   eventos distintos suficientemente distantes en embedding (umbral 0.85
   es estricto).

4. **Si en Fase 2.5 hace falta, lo añadimos.** El esquema soporta extensión:
   añadir tabla `senales_cluster_id` y un job de clustering periódico. La
   UI se acomoda. La inversión actual es deuda baja.

### Política de score reproducible

`scorer.score_compuesto(velocidad, volumen, freshness, intent, pesos, multiplicador_region)`
es una función **pura**. Misma entrada → misma salida, garantizado.

Componentes normalizados a [0, 1]:
- `velocidad`: `log10(1+v) / log10(1+100)` (saturación a 100/min).
- `volumen`: `log10(1+v) / log10(1+1M)` (saturación a 1M menciones).
- `freshness`: `exp(-horas / 24)` (tau de 24h).
- `intent`: pasa-a-través si viene del detector, default 0.5.

Suma ponderada → divide por suma de pesos → multiplica por `multiplicador_region`.
Test `test_misma_entrada_mismo_score` verifica la propiedad.

### Multiplicador de región (GTrends)

Para perfiles aragoneses, las señales de `ES-AR` se priorizan sobre `ES`
multiplicando el score base. Config en `fuentes_configuradas.config`:

```json
{
  "geos": [
    {"geo": "ES-AR", "peso": 0.7},
    {"geo": "ES",    "peso": 0.3}
  ]
}
```

Una señal trending nacional vista solo desde `ES` tendrá su score ×0.3
respecto a una vista en `ES-AR`. Si una misma señal aparece en ambos,
el dedupe la fusiona y se queda con el score máximo (regional).

## Paywall

Una fuente con `usar_solo_como_senal=TRUE` marca todas sus señales con
`paywall=TRUE`. En Fase 3, el nodo `research` excluirá esos artículos
del prompt del redactor. Solo cuentan para el scoring de tendencias.

Dominios marcados por defecto: Heraldo, El Periódico de Aragón, El País,
El Mundo, ABC, La Vanguardia (lista en `rss.py::_DOMINIOS_PAYWALL`).

## Budget hard-cap (X API)

`presupuestos_api(medio_id, servicio='x_api', budget_mensual_eur, ...)`.
Antes de cada llamada, `reservar` ejecuta:

```sql
UPDATE presupuestos_api
   SET gasto_mes_actual_eur = gasto_mes_actual_eur + $coste
 WHERE ... AND (gasto + $coste) <= (budget * 0.95)
RETURNING ...
```

Atómico. Si la fila no se devuelve, el budget no daba — abortamos. En
caso de error tras la reserva, `liberar` devuelve el importe.

## Cómo añadir un detector nuevo

1. Implementa `TrendDetector` en `workers/src/trends/<nombre>.py`.
2. Registra el `CHECK (detector IN (...))` en una nueva migración.
3. Añade al `_build_detector` de `cli.py`.
4. Test con HTTP mockeado en `workers/tests/trends/test_<nombre>.py`.
5. Documenta el formato de `config` aquí en este doc.

## Scheduling

En Fase 2-2.5: `.github/workflows/detect-signals.yml` con `cron: */15 * * * *`
sobre matrix de medios. La abstracción `JobScheduler` en
`workers/src/scheduler/` queda preparada para migrar a BullMQ sin tocar
detectores cuando montemos workers daemon.

## Schema final Fase 2

Fuente de verdad: `db/migrations/003_fase2_senales.sql`. Esta sección
resume QUÉ se creó, PARA QUÉ y QUÉ DIFIERE de la spec inicial.

### Tablas nuevas

| Tabla | Para qué sirve |
|---|---|
| `perfiles_deteccion` | Cada medio define N perfiles temáticos (`politica_aragon`, `deportes`, …). Lleva keywords obligatorias/negativas, país, idiomas, categoría destino y `ttl_dias`. Un perfil agrupa varias fuentes que comparten el mismo "interés editorial". |
| `fuentes_configuradas` | Por cada perfil, una fila por (detector, origen). Lleva el `cron_expr` del scheduler y un `config` JSONB libre que cada detector interpreta (RSS: `feeds[]`; GTrends: `geos[]`; etc.). El flag `usar_solo_como_senal` marca fuentes con paywall/copyright que solo cuentan para scoring de tendencia. |
| `presupuestos_api` | Hard cap mensual por (medio, servicio). `gasto_mes_actual_eur` se actualiza atómicamente. `mes_ref` es el primer día del mes para facilitar UPSERT mensual. |

### Cambios sobre la spec original

| Item | Spec inicial | Implementado | Razón |
|---|---|---|---|
| `perfiles_deteccion.keywords_obligatorias` | `TEXT[]` (nullable) | `NOT NULL DEFAULT ARRAY[]` | Evita rama `NULL vs lista vacía` en código. Una lista vacía expresa "sin filtro" igual de bien. |
| `perfiles_deteccion.keywords_negativas` | `TEXT[]` (nullable) | `NOT NULL DEFAULT ARRAY[]` | Mismo motivo. |
| `perfiles_deteccion.ttl_dias` | `INT NOT NULL DEFAULT 90` | + `CHECK (ttl_dias > 0)` | Defensivo: `ttl_dias = 0` o negativo no tiene sentido y haría desaparecer perfiles silenciosamente. |
| `fuentes_configuradas.detector` | sin restricción | `CHECK (detector IN ('rss','gtrends','gdelt','x'))` | Falla rápido si alguien intenta meter un detector inexistente. Cualquier nuevo detector requiere migración explícita. |
| `presupuestos_api.budget_mensual_eur` | `NUMERIC` | `NUMERIC(10,4) CHECK (> 0)` | 4 decimales para sumar costes muy pequeños (X read = 0.0046 €). Budget cero o negativo no tiene sentido. |
| `presupuestos_api.gasto_mes_actual_eur` | `NUMERIC` | `NUMERIC(10,4) DEFAULT 0 CHECK (>= 0)` | El CHECK garantiza que `liberar()` nunca deje saldo negativo aunque haya bugs en el caller. |
| Columna `hard_stop_fraccion` | Pensada como columna por-medio | **No existe** — hard-coded en `budget.py::UMBRAL_FRACCION = 0.95` | Decisión consciente: en Fase 2 todos los medios usan el mismo umbral. Si en Fase 5 hace falta por-medio, se añade columna y se lee desde código. Ver `docs/runbooks/budget.md`. |
| Columna `notificar_al_porcentaje` | Pensada para alertar al 80% | **Pospuesta** | No tenemos sistema de notificaciones todavía. Se añadirá junto con el canal (email/Slack) en Fase 7 o cuando aparezca un incidente real de coste. |

### Cambios en `senales` (ALTER)

Añadidas: `paywall`, `perfil_id`, `fuente_id`, `embedding vector(1024)`,
`url_origen`, `region`. Más detalle en CLAUDE.md §4.7.
