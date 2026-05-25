# Redactia — Sistema de Automatización Editorial

> Plataforma multi-tenant para detección de tendencias, generación, revisión
> y publicación automatizada de contenido editorial en medios digitales,
> con feedback loop de GSC y optimización nativa para Search y Discover.

---

## 1. Contexto y misión

**Qué construimos:** una plataforma SaaS multi-tenant que automatiza el flujo
editorial completo de un medio digital: detecta señales/tendencias, investiga
fuentes verificables, redacta artículos imitando el estilo de redactores
concretos del medio, genera o selecciona imágenes con licencia, publica al CMS
del medio (WordPress, OpenHost/OpenDemas, otros), y reentrena su priorización
de tendencias con métricas reales de GSC.

**Para quién:** medios digitales de tamaño pequeño-medio. Tenants iniciales:
Hoy Aragón, Diario de Huesca, Sports Aragón. Diseñada para escalar a 20-50
medios sin refactor de arquitectura.

**Lo que SÍ es:**
- Un orquestador multiagente con estado persistido (LangGraph + Postgres).
- Una herramienta de productividad para redactores humanos, no un sustituto.
- Una infraestructura editorial reutilizable, con CMS adapter pattern.

**Lo que NO es:**
- Un chatbot. No hay interfaz tipo ChatGPT.
- Un generador de contenido sin supervisión. Toda publicación pasa por
  política configurable (auto-publish, borrador, o bandeja editorial).
- Una herramienta de fake news. Las políticas de imagen y verificación son
  hard constraints, no recomendaciones.

**Estado actual:** bootstrap. Fase 1-2 del plan (`docs/plan.md`).

---

## 2. Stack técnico

| Capa | Tecnología | Justificación |
|---|---|---|
| Backend orquestación | Python 3.12 + FastAPI + LangGraph | Estado por nodo, retries, checkpoints |
| Backend API/dashboard | Next.js 15 (App Router, TypeScript) | SSR del dashboard, RSC, edge-friendly |
| Cola de jobs | BullMQ + Redis 7 | Bull-board para UI, mejor que Celery |
| Base de datos | PostgreSQL 16 + pgvector + pgcrypto | Embeddings, multi-tenant RLS |
| Modelos LLM | Claude Sonnet 4.7 (redacción/revisión), Haiku 4.5 (clasificación), Gemini 2.5 Flash (research con grounding) | |
| Embeddings | voyage-3-large | Mejor calidad para retrieval semántico |
| Imágenes generadas | Nano Banana 2 (default), GPT Image 2 (infografías con texto) | Ver `docs/image-policy.md` |
| Imágenes con licencia | Pexels, Unsplash, Pixabay (APIs) + integración futura EFE/Europa Press | |
| Search externo | Brave Search API + Gemini grounding | Brave para crawling, Gemini para verificación con citas |
| Frontend UI | shadcn/ui + Tailwind + Tiptap (editor) | |
| Charts/dashboards | Recharts + bull-board embedido | |
| Infra | Docker Compose (dev), Coolify o Hetzner Cloud (prod) | Hosting europeo por GDPR |
| Observabilidad | OpenTelemetry + Grafana + Loki | Trace cada run del pipeline |
| Tests | pytest (Python), vitest (TS), Playwright (e2e dashboard) | |

**Prohibido en este proyecto:**
- Vercel hosting para datos sensibles (multi-tenant, GDPR → infra europea propia).
- LangChain (usamos LangGraph directamente, sin la abstracción extra).
- Frameworks de UI agéntica (CrewAI, AutoGen). LangGraph + código explícito.
- ORMs pesados como SQLAlchemy con declarative_base. Usar SQLAlchemy 2.0 core
  o `asyncpg` directo con queries SQL escritas a mano. La capa de datos debe
  ser leíble y auditable.

---

## 3. Arquitectura general

```
                    ┌─────────────────────────────────────────┐
                    │      DASHBOARD (Next.js 15)             │
                    │  - Bandeja editorial                    │
                    │  - Configuración de automatizaciones    │
                    │  - Perfil de estilo por redactor        │
                    │  - Métricas y feedback                  │
                    └────────────────┬────────────────────────┘
                                     │ REST + Server Actions
                                     ▼
                    ┌─────────────────────────────────────────┐
                    │      API (FastAPI)                      │
                    │  - Auth, multi-tenant, RBAC             │
                    │  - CRUD: artículos, redactores, etc.    │
                    │  - Endpoints de control de pipeline     │
                    └────────────────┬────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
  ┌──────────┐              ┌──────────────┐             ┌─────────────┐
  │ Postgres │              │  Redis +     │             │  Storage    │
  │ pgvector │              │  BullMQ      │             │  (S3/MinIO) │
  └──────────┘              └──────┬───────┘             └─────────────┘
                                   │ jobs
                                   ▼
                    ┌─────────────────────────────────────────┐
                    │      WORKERS (Python + LangGraph)       │
                    │                                         │
                    │   ┌─────────────────────────────────┐   │
                    │   │ Pipeline Multiagente            │   │
                    │   │ detect → research → write →     │   │
                    │   │ review → enrich → publish       │   │
                    │   └─────────────────────────────────┘   │
                    │                                         │
                    │   - Trend detector (cron)               │
                    │   - Style profile builder (on-demand)   │
                    │   - GSC feedback loop (cron diario)     │
                    │   - Evergreen refresh (cron mensual)    │
                    └─────────────────────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────────────┐
                    │      CMS ADAPTERS                       │
                    │  - WordPress REST                       │
                    │  - OpenHost / OpenDemas                 │
                    │  - (futuro: otros)                      │
                    └─────────────────────────────────────────┘
```

**Principios arquitectónicos:**

1. **El estado vive en Postgres, no en memoria.** Cualquier worker debe poder
   morir y otro retomar desde el último checkpoint.
2. **Idempotencia.** Cada nodo del pipeline acepta ser reejecutado sin efectos
   duplicados. Usar `run_id + step_id` como clave única.
3. **Trazabilidad total.** Cada run del pipeline guarda input, output y prompt
   exacto de cada nodo. Para auditoría editorial y debugging.
4. **Multi-tenant por defecto.** Toda query lleva `medio_id`. RLS de Postgres
   activado. Nunca cross-tenant queries en código de aplicación.
5. **Política antes que IA.** Las hard policies (imagen, copyright, privacidad)
   se ejecutan ANTES de invocar al LLM cuando es posible, y se validan DESPUÉS
   con un agente verificador.

---

## 4. Modelo de datos

Esquema inicial en `db/migrations/001_initial.sql`. Resumen aquí.

### 4.1 Tenancy y usuarios

```sql
medios (
  id              UUID PRIMARY KEY,
  slug            TEXT UNIQUE NOT NULL,   -- 'hoy-aragon', 'sports-aragon'
  nombre          TEXT NOT NULL,
  cms_tipo        TEXT NOT NULL,          -- 'wordpress' | 'opendemas' | 'custom'
  cms_config      JSONB NOT NULL,         -- URL, API keys cifradas con pgcrypto
  style_guide_md  TEXT,                   -- guía editorial del medio (opcional)
  activo          BOOLEAN DEFAULT TRUE,
  creado_at       TIMESTAMPTZ DEFAULT NOW()
);

usuarios (
  id              UUID PRIMARY KEY,
  email           TEXT UNIQUE NOT NULL,
  nombre          TEXT NOT NULL,
  password_hash   TEXT NOT NULL,
  rol_global      TEXT,                   -- 'superadmin' | NULL
  creado_at       TIMESTAMPTZ DEFAULT NOW()
);

usuarios_medios (
  usuario_id      UUID REFERENCES usuarios(id),
  medio_id        UUID REFERENCES medios(id),
  rol             TEXT NOT NULL,          -- 'editor_jefe' | 'redactor' | 'colaborador'
  PRIMARY KEY (usuario_id, medio_id)
);
```

**RLS activado** en todas las tablas con `medio_id`. Policy estándar:
`USING (medio_id = current_setting('app.medio_actual')::uuid)`.

### 4.2 Redactores y estilo

```sql
redactores (
  id              UUID PRIMARY KEY,
  medio_id        UUID REFERENCES medios(id) NOT NULL,
  usuario_id      UUID REFERENCES usuarios(id),  -- NULL si redactor "virtual"
  nombre_publico  TEXT NOT NULL,           -- aparece como autor
  activo          BOOLEAN DEFAULT TRUE
);

estilos_redactor (
  id              UUID PRIMARY KEY,
  redactor_id     UUID REFERENCES redactores(id) NOT NULL,
  version         INT NOT NULL,            -- v1, v2, v3... incrementa con cada regen
  guia_estilo_md  TEXT NOT NULL,           -- markdown estructurado
  metricas        JSONB NOT NULL,          -- long media frase/párrafo, ratios, etc.
  generado_at     TIMESTAMPTZ DEFAULT NOW(),
  activo          BOOLEAN DEFAULT FALSE,   -- solo una versión activa por redactor
  UNIQUE (redactor_id, version)
);

ejemplos_redactor (
  id              UUID PRIMARY KEY,
  redactor_id     UUID REFERENCES redactores(id) NOT NULL,
  texto_completo  TEXT NOT NULL,
  titulo          TEXT,
  url_origen      TEXT,
  fecha_pub       DATE,
  embedding       vector(1024),
  pegado_at       TIMESTAMPTZ DEFAULT NOW()
);

variantes_tematicas_redactor (
  redactor_id     UUID REFERENCES redactores(id),
  tema_codigo     TEXT NOT NULL,           -- 'politica_local', 'deportes', etc.
  ajustes_md      TEXT NOT NULL,
  PRIMARY KEY (redactor_id, tema_codigo)
);

correcciones_redactor (
  id              UUID PRIMARY KEY,
  draft_id        UUID REFERENCES drafts(id),
  redactor_id     UUID REFERENCES redactores(id),
  diff            JSONB NOT NULL,          -- estructura: {section, before, after}
  categoria       TEXT NOT NULL,           -- 'tono' | 'estructura' | 'vocab' | 'factual'
  creado_at       TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.3 Señales, fuentes y temas

```sql
senales (
  id              UUID PRIMARY KEY,
  medio_id        UUID REFERENCES medios(id) NOT NULL,
  origen          TEXT NOT NULL,           -- 'gtrends' | 'x' | 'gdelt' | 'gsc' | 'rss'
  termino         TEXT NOT NULL,
  pais            TEXT,
  categoria       TEXT,
  score           NUMERIC(6,3) NOT NULL,   -- score compuesto
  velocidad       NUMERIC,                 -- delta/min
  volumen         INT,
  metadatos       JSONB,
  detectado_at    TIMESTAMPTZ DEFAULT NOW(),
  expira_at       TIMESTAMPTZ,             -- señal "fresca" durante N horas
  -- añadidos en Fase 2 (migración 003):
  paywall         BOOLEAN NOT NULL DEFAULT FALSE,  -- fuente con paywall: NO citar en redacción
  perfil_id       UUID REFERENCES perfiles_deteccion(id) ON DELETE SET NULL,
  fuente_id       UUID REFERENCES fuentes_configuradas(id) ON DELETE SET NULL,
  embedding       vector(1024),            -- dedupe semántico (HNSW)
  url_origen      TEXT,
  region          TEXT                     -- 'ES', 'ES-AR', ...
);

fuentes_run (
  id              UUID PRIMARY KEY,
  run_id          UUID REFERENCES runs(id) NOT NULL,
  url             TEXT NOT NULL,
  titulo          TEXT,
  publicado_at    TIMESTAMPTZ,
  autoridad_score NUMERIC,                 -- score de autoridad del dominio
  contenido_md    TEXT,                    -- extracto/resumen, no full text
  citado_en_articulo BOOLEAN DEFAULT FALSE
);
```

#### Tablas de Fase 2 (detección)

Fuente de verdad: `db/migrations/003_fase2_senales.sql`. Estos son los
schemas **reales**, no las specs originales (que pasaron por refinamientos
durante la implementación — ver `docs/agents/trend_detector.md` §"Schema final Fase 2").

```sql
perfiles_deteccion (
  id                    UUID PRIMARY KEY,
  medio_id              UUID REFERENCES medios(id) NOT NULL,
  nombre                TEXT NOT NULL,
  descripcion           TEXT,
  pais                  TEXT NOT NULL DEFAULT 'ES',
  idiomas               TEXT[] NOT NULL DEFAULT ARRAY['es'],
  keywords_obligatorias TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  keywords_negativas    TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  categoria_destino     TEXT NOT NULL,
  activo                BOOLEAN NOT NULL DEFAULT TRUE,
  ttl_dias              INT NOT NULL DEFAULT 90 CHECK (ttl_dias > 0),
  creado_at             TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (medio_id, nombre)
);

fuentes_configuradas (
  id                    UUID PRIMARY KEY,
  medio_id              UUID REFERENCES medios(id) NOT NULL,
  perfil_id             UUID REFERENCES perfiles_deteccion(id) NOT NULL,
  detector              TEXT NOT NULL CHECK (detector IN ('rss','gtrends','gdelt','x')),
  origen_url            TEXT,                       -- URL principal cuando aplica (RSS)
  cron_expr             TEXT NOT NULL,
  config                JSONB NOT NULL DEFAULT '{}',
  usar_solo_como_senal  BOOLEAN NOT NULL DEFAULT FALSE,
  activo                BOOLEAN NOT NULL DEFAULT TRUE,
  creado_at             TIMESTAMPTZ DEFAULT NOW(),
  ultima_ejec_at        TIMESTAMPTZ,
  ultima_ejec_estado    TEXT
);

-- Cap mensual por servicio externo. No hay columna `hard_stop_fraccion`:
-- el umbral (0.95) está hard-coded en workers/src/trends/budget.py.
-- Ver docs/runbooks/budget.md.
presupuestos_api (
  id                    UUID PRIMARY KEY,
  medio_id              UUID REFERENCES medios(id) NOT NULL,
  servicio              TEXT NOT NULL,              -- 'x_api', 'voyage', ...
  budget_mensual_eur    NUMERIC(10,4) NOT NULL CHECK (budget_mensual_eur > 0),
  gasto_mes_actual_eur  NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (gasto_mes_actual_eur >= 0),
  mes_ref               DATE NOT NULL,              -- primer día del mes
  actualizado_at        TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (medio_id, servicio, mes_ref)
);
```

Todas con RLS + FORCE + WITH CHECK por `medio_id`, y grants a `redactia_app`.

### 4.4 Runs, drafts y artículos

```sql
runs (
  id              UUID PRIMARY KEY,
  medio_id        UUID REFERENCES medios(id) NOT NULL,
  redactor_id     UUID REFERENCES redactores(id),
  trigger_tipo    TEXT NOT NULL,           -- 'manual' | 'automatizacion' | 'evergreen'
  trigger_id      UUID,                    -- referencia a automatizacion si aplica
  senal_id        UUID REFERENCES senales(id),
  tema_input      TEXT,                    -- tema/topic introducido manualmente
  categoria       TEXT,
  estado          TEXT NOT NULL,           -- 'pendiente' | 'ejecutando' | 'completado' | 'fallido'
  iniciado_at     TIMESTAMPTZ DEFAULT NOW(),
  finalizado_at   TIMESTAMPTZ,
  coste_eur       NUMERIC(8,4)             -- coste real de APIs en este run
);

run_steps (
  id              UUID PRIMARY KEY,
  run_id          UUID REFERENCES runs(id) NOT NULL,
  step_nombre     TEXT NOT NULL,           -- 'research' | 'write' | 'review' | ...
  estado          TEXT NOT NULL,
  input           JSONB,
  output          JSONB,
  prompt_usado    TEXT,                    -- prompt completo enviado al LLM
  modelo          TEXT,                    -- 'claude-sonnet-4-7-20260...'
  tokens_in       INT,
  tokens_out      INT,
  duracion_ms     INT,
  error           TEXT,
  iniciado_at     TIMESTAMPTZ,
  finalizado_at   TIMESTAMPTZ
);

drafts (
  id              UUID PRIMARY KEY,
  run_id          UUID REFERENCES runs(id) NOT NULL,
  medio_id        UUID REFERENCES medios(id) NOT NULL,
  titulo          TEXT NOT NULL,
  meta_title      TEXT,                    -- separado del H1
  meta_descr      TEXT,
  slug            TEXT,
  cuerpo_md       TEXT NOT NULL,
  cuerpo_html     TEXT,                    -- generado al publicar
  entidades       JSONB,                   -- [{tipo, nombre, wikidata_id, ...}]
  enlaces_internos JSONB,                  -- [{anchor, articulo_id, score}]
  imagen_destacada_id UUID REFERENCES imagenes_articulo(id),
  schema_jsonld   JSONB,                   -- NewsArticle schema
  estado          TEXT NOT NULL,           -- 'borrador' | 'aprobado' | 'publicado' | 'rechazado' | 'programado'
  motivo_rechazo  TEXT,
  similitud_max   NUMERIC,                 -- vs últimos 90 días (canibalización check)
  creado_at       TIMESTAMPTZ DEFAULT NOW(),
  programado_para TIMESTAMPTZ,
  publicado_at    TIMESTAMPTZ,
  cms_url         TEXT,                    -- URL final en el CMS
  cms_id_externo  TEXT                     -- ID del post en el CMS
);

imagenes_articulo (
  id              UUID PRIMARY KEY,
  draft_id        UUID REFERENCES drafts(id) NOT NULL,
  storage_path    TEXT NOT NULL,
  url_publica     TEXT,
  fuente          TEXT NOT NULL,           -- 'banco_licencia' | 'nano_banana_2' | 'gpt_image_2' | 'manual'
  prompt_usado    TEXT,
  modelo_version  TEXT,
  c2pa_metadata   JSONB,
  synthid_present BOOLEAN,
  alt_text        TEXT NOT NULL,
  pie_foto        TEXT NOT NULL,
  declaracion_ia_visible BOOLEAN NOT NULL,
  banco_licencia_id TEXT,                  -- ID externo si es de banco
  banco_licencia_tipo TEXT,                -- 'pexels' | 'unsplash' | 'efe' | ...
  creado_at       TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.5 Automatizaciones y feedback

```sql
automatizaciones (
  id              UUID PRIMARY KEY,
  medio_id        UUID REFERENCES medios(id) NOT NULL,
  nombre          TEXT NOT NULL,
  tipo            TEXT NOT NULL,           -- 'senales' | 'tematica'
  cron_expr       TEXT NOT NULL,
  config          JSONB NOT NULL,          -- {categoria, n_articulos, redactor_id, estilo_id, auto_publish}
  activo          BOOLEAN DEFAULT TRUE,
  creado_at       TIMESTAMPTZ DEFAULT NOW(),
  ultima_ejec_at  TIMESTAMPTZ
);

gsc_metricas (
  id              UUID PRIMARY KEY,
  medio_id        UUID REFERENCES medios(id) NOT NULL,
  draft_id        UUID REFERENCES drafts(id),
  url             TEXT NOT NULL,
  fecha           DATE NOT NULL,
  impresiones     INT,
  clicks          INT,
  ctr             NUMERIC,
  posicion        NUMERIC,
  fuente          TEXT NOT NULL,           -- 'search' | 'discover'
  capturado_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (draft_id, fecha, fuente)
);

scoring_pesos (
  id              UUID PRIMARY KEY,
  medio_id        UUID REFERENCES medios(id) NOT NULL,
  categoria       TEXT NOT NULL,
  peso_velocidad  NUMERIC NOT NULL DEFAULT 1.0,
  peso_volumen    NUMERIC NOT NULL DEFAULT 1.0,
  peso_freshness  NUMERIC NOT NULL DEFAULT 1.0,
  peso_intent     NUMERIC NOT NULL DEFAULT 1.0,
  actualizado_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.6 Catálogo de entidades

```sql
entidades_catalogo (
  id              UUID PRIMARY KEY,
  medio_id        UUID REFERENCES medios(id),   -- NULL = global
  tipo            TEXT NOT NULL,           -- 'persona' | 'organizacion' | 'lugar' | 'evento'
  nombre_canonico TEXT NOT NULL,
  aliases         TEXT[],                  -- variantes y diminutivos
  wikidata_id     TEXT,
  contexto_md     TEXT,                    -- "alcalde de Zaragoza desde 2019..."
  embedding       vector(1024),
  activo          BOOLEAN DEFAULT TRUE,
  creado_at       TIMESTAMPTZ DEFAULT NOW()
);
```

Catálogo inicial para Aragón: figuras políticas (alcaldes capitales de
provincia, presidente DGA, consejeros), municipios cabeceras de comarca,
eventos recurrentes (Pilares, Cincomarzada, Vuelta a Aragón, Aragón Open
Future), empresas IBEX con sede en Aragón, principales clubes deportivos.
Cargar desde `db/seeds/entidades_aragon.sql`.

---

## 5. Especificación del pipeline multiagente

Implementado como grafo de LangGraph en `workers/pipeline/graph.py`. Cada
nodo es una función pura `(state) -> state`. El grafo envuelve cada nodo
con `_ejecutar_step` (vía `persistence.with_step`) para persistir input
y output COMPACTOS en `run_steps` — trazabilidad completa para auditoría
editorial y base para la UI de la bandeja. Los compactadores viven en
`workers/src/pipeline/step_payloads.py`: persisten metadatos (conteos,
URLs, IDs, títulos truncados a 500 chars), nunca blobs grandes
(`cuerpo_md` íntegro, `contenido_md` de fuentes, ejemplos cargados).

```
   detect ──► research ──► write ──► review ──► enrich ──► publish
                                       │
                                       └─► (loop si falla validación)
```

### 5.1 Nodo `detect`

**Input:** `{medio_id, trigger_tipo, senal_id?, tema_input?, categoria?}`

**Responsabilidad:** consolidar QUÉ se va a escribir. Si viene de
automatización por señales, toma la señal con score más alto que no haya
sido ya cubierta en las últimas 24h. Si es disparo manual, simplemente
empaqueta el tema dado.

**Output:** `{tema_final: str, angulo: str, urgencia: 'breaking'|'normal'|'evergreen'}`

**Modelo:** Haiku 4.5 (clasificación rápida).

**Checks:**
- Canibalización: vector search contra `drafts` publicados últimos 30 días.
  Si similitud > 0.85, marcar el run como `tipo: actualizacion` y pasar el
  `draft_id` original al siguiente nodo (modo refresh, no creación nueva).

### 5.2 Nodo `research`

**Input:** `{tema_final, angulo, medio_id}`

**Responsabilidad:** recopilar fuentes verificables y extraer hechos.

**Sub-tareas:**
1. Búsqueda web vía Brave API + Gemini grounding.
2. Filtrar dominios por `autoridad_score`. Lista negra dura: agregadores
   anónimos, foros, redes sociales sin verificación, sitios con historial
   de desinformación (ver `data/blacklist_dominios.txt`).
3. Para top 5-8 fuentes, hacer fetch del contenido completo (respetando
   robots.txt y rate limits).
4. Llamar a Gemini 2.5 Flash con grounding para sintetizar los hechos
   verificados con citas.
5. Extraer entidades nombradas (NER) y mapearlas al `entidades_catalogo`.

**Output:** `{fuentes: [...], hechos_verificados: [...], entidades: [...], citas: [...]}`

**Hard constraints:**
- Nunca menos de 3 fuentes independientes para hechos noticiosos.
- Para temas evergreen, mínimo 2 fuentes.
- Si no se alcanza el mínimo, abortar el run con estado `fuentes_insuficientes`.

### 5.3 Nodo `write`

**Input:** `{tema, hechos_verificados, entidades, redactor_id, estilo_id, variante_tematica?}`

**Responsabilidad:** redactar el artículo imitando el estilo del redactor
asignado.

**Construcción del prompt:**
```
<system>
Eres {redactor.nombre_publico}, redactor de {medio.nombre}.
Sigue estrictamente tu guía de estilo y tu voz.
NUNCA inventes hechos. Solo usa los hechos verificados que se te pasan.
</system>

<style_guide>
{estilo_redactor.guia_estilo_md}
</style_guide>

<variante_tematica activo_si_aplica>
{variante.ajustes_md}
</variante_tematica>

<correcciones_recientes>
{ultimas_20_correcciones_categorizadas_aplicables}
</correcciones_recientes>

<ejemplos>
{3-5 ejemplos del propio redactor más cercanos en embedding al tema}
</ejemplos>

<hechos_verificados>
{lista numerada, cada uno con cita a fuente}
</hechos_verificados>

<entidades>
{nombre canónico, contexto, wikidata_id}
</entidades>

<output_format>
JSON con: titulo, meta_title, meta_descr, slug, cuerpo_md, entidades_referidas
</output_format>
```

**Modelo:** Claude Sonnet 4.7.

**Reglas hard:**
- Cuerpo entre 350 y 1200 palabras según `tipo` (breaking más corto, evergreen
  más largo).
- Todo hecho concreto debe trazarse a una fuente del input. Validación en el
  nodo `review`.
- H2s descriptivos, evitar clickbait. Sentence case.
- Meta title diferente del H1 (Discover lo agradece).
- Slug optimizado, sin stopwords, máximo 60 caracteres.

**Política editorial: medios competidores** (también enforced en `review`)

El cuerpo del artículo NO menciona a otros medios digitales por su nombre
NI inserta enlaces markdown a dominios competidores. La estrategia
prioriza enlace INTERNO (que añade `enrich`) o a fuentes
institucionales/agencias. Los enlaces externos son OPCIONALES desde
v1.2.0; el contenido bien escrito vale más que un enlace forzado.

Dos vertientes (estrictas, ambas bloqueantes):

1) **Sin nombres de competidores en el cuerpo.** Prohibidos nominalmente:
   El Periódico de Aragón, El Español, Heraldo (de Aragón), Aragón
   Digital, 20minutos, El País, El Mundo, ABC, La Razón, CARTV, etc.
   Lista en `workers/src/pipeline/nodes/review.py`
   (`LISTA_MEDIOS_COMPETIDORES`).

2) **Sin URLs de dominios competidores en enlaces markdown** — ni con
   anchor neutral. Dominios bloqueados: `elperiodicodearagon.com`,
   `elespanol.com`, `heraldo.es`, `aragondigital.es`, `20minutos.es`,
   `elpais.com`, `elmundo.es`, `abc.es`, `larazon.es`, `cartv.es`.
   Lista en `DOMINIOS_COMPETIDORES` (mismo fichero).

Permitido nominalmente y enlazable:
- **Agencias de noticias:** EFE, Europa Press, Reuters, AP, AFP.
- **Fuentes institucionales:** BOE, BOA, Ayuntamiento de Zaragoza, DGA,
  Gobierno de Aragón/España, ministerios, INE.
- **El propio medio destino** (auto-referencia, caso raro).

Aunque el cuerpo no enlace a fuentes competidoras, el `contenido_md`
de TODAS las fuentes (incluidas las del competidor) sí se pasa a `write`
y `review` como contexto (`fuentes_contenido`), para que el redactor
disponga de los detalles ricos del tema.

Enforcement:
- En `write`: el prompt instruye con ejemplos CORRECTO/INCORRECTO de
  ambas vertientes y una verificación final previa al JSON.
- En `review`: dos checks Python (`_detectar_menciones_competidores` para
  nombres, `_detectar_urls_competidores` para dominios) + prompt Haiku
  reforzado. Cualquiera marca `errores_estilo` (bloqueante para retry).

En Fase 4 esta lista se moverá a una tabla `medios_competencia` por
`medio_id` (la lista varía por cliente: lo que es competencia de Hoy
Aragón no lo es necesariamente para un medio nacional).

### 5.4 Nodo `review`

**Input:** `{draft generado, hechos_verificados, fuentes}`

**Responsabilidad:** validar el draft antes de seguir.

**Checks automáticos (sin LLM):**
- Longitud en rango.
- Slug válido.
- Meta title ≤ 60 chars, meta descr 140-160 chars.
- URLs citadas existen en `state.fuentes` (defensa contra invención de URLs).
- Enlaces markdown a dominios competidores → bloqueante (CLAUDE.md §5.3).
- Menciones nominales a competidores en el cuerpo → bloqueante (§5.3).
- Markdown válido (sin H1).
- El mínimo de citas inline NO es bloqueante desde v1.2.0: si el cuerpo
  no enlaza a fuentes, el nodo emite una sugerencia, no un error. La
  estrategia prioriza enlace INTERNO (lo añade `enrich`).

**Checks con LLM (agente verificador, Haiku):**
- Cada afirmación factual del cuerpo aparece en `hechos_verificados` O en
  el `contenido_md` íntegro de las fuentes pasado al LLM como
  `fuentes_contenido`. Solo si NO aparece en ninguno se marca como
  invención (CLAUDE.md §5.3). Los `hechos` son los titulares
  sintetizados; `fuentes_contenido` tiene los detalles ricos.
- No hay menciones a personas reales sin contexto verificado.
- Tono y registro coherentes con la `style_guide`. Los rangos del
  style_guide ("frase media 18-25 palabras") son OBJETIVOS estadísticos,
  no topes estrictos. Una frase aislada de 30 palabras no es error si
  la media global está en rango.

**Output:** `{aprobado: bool, errores: [...], sugerencias: [...]}`

**Si no aprobado:** un reintento (regenera con feedback). Si vuelve a fallar,
el draft pasa a bandeja editorial con flag `requiere_revision_humana`.

### 5.5 Nodo `enrich`

**Input:** `{draft aprobado, entidades, medio_id}`

**Responsabilidad:** capa SEO/Discover.

**Sub-tareas:**
1. **Tags/etiquetas:** mapear entidades al sistema de tags del CMS. Si el CMS
   no tiene la tag aún, crearla via API (si el adapter lo soporta).
2. **Internal linking:** para cada párrafo, vector search en `drafts` publicados
   últimos 180 días, top 3 más relevantes (similitud > 0.7). Decidir qué
   linkar (máximo 4 enlaces internos por artículo) y dónde insertarlos.
3. **JSON-LD NewsArticle:** generar schema completo con `mainEntity` apuntando
   a entidades, `datePublished`, `dateModified`, `author`, `publisher`.
4. **Imagen destacada:** invocar router de imagen (ver §6 política de imagen).
5. **Open Graph + Twitter cards.**

**Output:** draft enriquecido completo, listo para publicar.

### 5.6 Nodo `publish`

**Input:** `{draft enriquecido, medio_id, modo_publish}`

**Responsabilidad:** publicar (o no) según la política.

Modos:
- `auto`: publica directamente en el CMS.
- `borrador_cms`: envía al CMS como borrador (visible para los redactores
  desde el CMS nativo).
- `bandeja`: queda en Redactia, en bandeja editorial.
- `programado`: respeta `programado_para`.

**CMS adapter:** carga el adapter correspondiente (`cms_tipo`) y ejecuta
`adapter.publish(draft)`. El adapter es responsable de mapear tags/categorías
y subir imágenes al storage del CMS si es necesario.

**Post-publicación:**
- Guardar `cms_url` y `cms_id_externo`.
- Trigger del worker de `gsc_capture` programado a 24h, 72h, 7d, 30d.
- Notificar al redactor humano vía email si está suscrito a notificaciones.

---

## 6. Políticas críticas (hard constraints, no negociables)

### 6.1 Política de imagen

Definición completa en `docs/image-policy.md`. Resumen aquí.

**Prohibido por defecto:**
- Generar fotorrealismo de personas reales identificables en contextos no
  documentados (ej. "Sánchez en una rueda de prensa" cuando esa rueda de
  prensa no ha sido cubierta por fotoperiodismo).
- Recrear eventos noticiosos específicos como si fueran fotos.
- Cualquier imagen que pueda confundirse con fotoperiodismo.

**Permitido:**
- Conceptos abstractos (manos sobre teclado, billetes, balanza de justicia).
- Ilustración editorial declarada (estilo ilustración, no foto).
- Infografías y data viz con texto integrado (aquí GPT Image 2 brilla).
- Composiciones de objetos y lugares genéricos no identificables.

**Router de imagen** (orden de prioridad):
1. Si el artículo tiene sujeto humano real identificable o evento noticioso
   específico → ruta "banco con licencia". Si no encuentra, marca el draft
   como `requiere_imagen_humana` y avisa al redactor.
2. Si es infografía/gráfico/imagen con texto integrado → GPT Image 2.
3. Si es conceptual/ilustrativo → Nano Banana 2.

**Toda imagen IA debe llevar:**
- SynthID watermark (automático en Nano Banana y GPT Image 2).
- C2PA Content Credentials en metadata.
- Alt text con declaración explícita: "Imagen ilustrativa generada con IA".
- Pie de foto VISIBLE al lector con la misma declaración.
- Registro en `imagenes_articulo` con prompt y modelo usado.

### 6.2 Política de copyright

- Nunca reproducir > 15 palabras textuales de una fuente externa.
- Máximo una cita textual por fuente.
- Resto siempre parafraseado en palabras propias del redactor.
- Nunca reproducir letras de canciones, poemas o haikus.
- Si la fuente solo está disponible tras paywall, no se usa salvo que el
  medio tenga licencia explícita (registrar en `licencias_fuentes`).

### 6.3 Política de privacidad y GDPR

- Datos personales de redactores cifrados en reposo con pgcrypto.
- API keys de CMSs y servicios externos en columna `cms_config` cifrada.
- Logs no almacenan contenido completo de artículos no publicados.
- Retención de runs fallidos: 30 días.
- Hosting en infraestructura europea (Hetzner FRA o similar).
- Cookies del dashboard: solo session + CSRF. No tracking de terceros.

### 6.4 Política multi-tenant

- RLS de Postgres activado en todas las tablas con `medio_id`.
- Toda función SQL declara `SET app.medio_actual` al inicio del request.
- Nunca queries cross-tenant en código de aplicación. Si hace falta un dato
  global (catálogo de entidades sin `medio_id`), usar función `SECURITY DEFINER`
  explícita.
- Storage particionado por `medio_id` (bucket o prefijo).
- Logs y métricas etiquetadas con `medio_id` en OpenTelemetry.

### 6.5 Política de transparencia editorial

- Pie de página del medio debe declarar uso de IA en la producción de
  contenido (responsabilidad del medio, no de Redactia).
- Cada artículo generado por Redactia incluye en su JSON-LD un campo
  `creator.@type: "Organization"` con el medio, no la IA. El redactor humano
  asignado figura como `author`.
- Cuando un artículo es 100% IA sin edición humana, se incluye un disclaimer
  configurable a nivel medio (ON/OFF por tenant).

---

## 7. Convenciones de código

### 7.1 Python (workers, pipeline)

- Python 3.12+, type hints estrictos en todo código nuevo.
- `pyproject.toml` con `ruff` (lint + format) y `mypy --strict`.
- Funciones puras donde sea posible. Side effects centralizados en módulos
  `*/io.py` o `*/persistence.py`.
- Async por defecto. Bloqueante solo cuando es estrictamente necesario.
- Logs estructurados con `structlog`. Nunca `print`.
- Nada de `from x import *`.

```python
# Estilo de función de nodo del pipeline
async def write_node(state: PipelineState, deps: Deps) -> PipelineState:
    """Redacta el artículo según el estilo del redactor asignado."""
    ...
```

### 7.2 TypeScript (Next.js, dashboard)

- TypeScript strict mode, `noUncheckedIndexedAccess: true`.
- Server Components por defecto. Client Components solo si interactividad.
- Server Actions para mutaciones.
- Zod para validación de inputs en boundaries (formularios, APIs).
- No `any`. Si no se conoce el tipo, `unknown` y narrow.
- Hooks personalizados en `lib/hooks/`. Tipos compartidos en `lib/types/`.

### 7.3 SQL

- Snake_case en todo (tablas, columnas, índices).
- Migraciones numeradas, idempotentes donde sea posible.
- Comentarios SQL en español explicando intención de tabla y columnas no obvias.
- Índices declarados explícitamente, no se asume nada.
- Constraints (FK, UNIQUE, CHECK) nombrados de forma legible.

### 7.4 Naming general

- Nombres de funciones en español o inglés, consistentes dentro del módulo.
  Por defecto: dominio de negocio en español (`detectar_senales`, `aprobar_draft`),
  infraestructura en inglés (`build_redis_client`, `parse_response`).
- Nombres de variables en inglés (estándar de la industria).
- Comentarios en español.
- Mensajes de error y logs operativos en español (los ve el equipo de Dani).
- Mensajes de error técnico interno (excepciones Python) en inglés.

### 7.5 Tests

- Cada agente del pipeline tiene tests unitarios con fixtures realistas en
  `tests/fixtures/`. Mock de LLMs con respuestas grabadas.
- Tests de integración end-to-end en `tests/e2e/` que ejercitan el grafo
  completo con un LLM real (etiquetados `@pytest.mark.live`, no corren en CI
  por defecto).
- Playwright para flujos críticos del dashboard: login, pegar artículos de
  estilo, aprobar draft, configurar automatización.

### 7.6 Commits y branches

- Conventional commits en inglés: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`.
- Branch naming: `feat/<scope>-<short-desc>`, `fix/...`, `chore/...`.
- PRs pequeños. Si una feature es grande, descomponer en sub-PRs.

---

## 8. Estructura de carpetas

```
redactia/
├── CLAUDE.md                    # este archivo
├── README.md                    # quick start humano
├── docker-compose.yml           # dev: postgres, redis, minio, app
├── docker-compose.prod.yml      # prod: misma stack + traefik
├── .env.example
│
├── api/                         # FastAPI: REST API
│   ├── pyproject.toml
│   ├── src/
│   │   ├── main.py
│   │   ├── auth/
│   │   ├── tenancy/             # RLS, contexto multi-tenant
│   │   ├── routes/
│   │   ├── schemas/             # Pydantic
│   │   └── db/
│   └── tests/
│
├── workers/                     # Python: pipeline + cron jobs
│   ├── pyproject.toml
│   ├── src/
│   │   ├── pipeline/
│   │   │   ├── graph.py         # LangGraph definition
│   │   │   ├── nodes/
│   │   │   │   ├── detect.py
│   │   │   │   ├── research.py
│   │   │   │   ├── write.py
│   │   │   │   ├── review.py
│   │   │   │   ├── enrich.py
│   │   │   │   └── publish.py
│   │   │   ├── state.py         # PipelineState (TypedDict / Pydantic)
│   │   │   └── prompts/
│   │   ├── cms_adapters/
│   │   │   ├── base.py          # interfaz abstracta
│   │   │   ├── wordpress.py
│   │   │   ├── opendemas.py
│   │   │   └── tests/
│   │   ├── image/
│   │   │   ├── policy.py
│   │   │   ├── router.py
│   │   │   ├── nano_banana.py
│   │   │   ├── gpt_image.py
│   │   │   └── banks.py         # Pexels, Unsplash, etc.
│   │   ├── style_profile/
│   │   │   ├── builder.py       # extrae style guide de ejemplos
│   │   │   ├── updater.py       # regenera con correcciones
│   │   │   └── metrics.py       # métricas objetivas
│   │   ├── trends/
│   │   │   ├── gtrends.py
│   │   │   ├── x_api.py
│   │   │   ├── gdelt.py
│   │   │   └── scorer.py
│   │   ├── gsc/
│   │   │   ├── capture.py
│   │   │   └── feedback_loop.py
│   │   └── llm/
│   │       ├── claude.py
│   │       ├── gemini.py
│   │       └── embeddings.py
│   └── tests/
│
├── dashboard/                   # Next.js 15
│   ├── package.json
│   ├── app/
│   │   ├── (auth)/
│   │   ├── (app)/
│   │   │   ├── bandeja/
│   │   │   ├── senales/
│   │   │   ├── redactores/
│   │   │   ├── automatizaciones/
│   │   │   ├── metricas/
│   │   │   └── ajustes/
│   │   └── api/
│   ├── components/
│   │   └── ui/                  # shadcn
│   ├── lib/
│   └── tests/
│
├── db/
│   ├── migrations/
│   │   ├── 001_initial.sql
│   │   ├── 002_*.sql
│   │   └── ...
│   └── seeds/
│       ├── entidades_aragon.sql
│       └── blacklist_dominios.txt
│
├── docs/
│   ├── plan.md                  # roadmap completo, fases
│   ├── image-policy.md
│   ├── agents/                  # spec detallada de cada agente
│   ├── cms-adapters/            # cómo añadir un adapter
│   ├── style-guides-format.md
│   ├── prompts/                 # versionado de prompts
│   └── runbooks/                # ops, troubleshooting
│
└── scripts/
    ├── seed_dev.py
    ├── reset_db.sh
    └── load_entidades.py
```

---

## 9. Servicios externos y variables de entorno

```bash
# Base
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
STORAGE_ENDPOINT=https://...
STORAGE_BUCKET=redactia-dev
STORAGE_ACCESS_KEY=...
STORAGE_SECRET_KEY=...

# LLMs
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
OPENAI_API_KEY=...                   # solo para GPT Image 2
VOYAGE_API_KEY=...

# Search
BRAVE_SEARCH_API_KEY=...

# Trends
X_API_BEARER_TOKEN=...               # tier básico
GTRENDS no requiere key

# Bancos de imagen
PEXELS_API_KEY=...
UNSPLASH_ACCESS_KEY=...
PIXABAY_API_KEY=...

# GSC (OAuth por medio)
GSC_OAUTH_CLIENT_ID=...
GSC_OAUTH_CLIENT_SECRET=...

# Auth dashboard
AUTH_SECRET=...
NEXTAUTH_URL=...
```

Por cada medio (tenant), las credenciales del CMS se guardan en `medios.cms_config`
cifradas con pgcrypto. Nunca en `.env`.

---

## 10. Workflow de desarrollo

### 10.1 Plan de fases

Ver `docs/plan.md`. Resumen:

- **Fase 1 (sem 1-2):** cimientos. Esquema BD + auth + multi-tenant.
- **Fase 2 (sem 3):** trend detector + dashboard de señales.
- **Fase 3 (sem 4-5):** pipeline multiagente básico (sin estilo personalizado).
- **Fase 4 (sem 6):** style profile por redactor + loop de correcciones.
- **Fase 5 (sem 7):** CMS adapters (WordPress + OpenHost/OpenDemas).
- **Fase 6 (sem 8):** capa SEO/Discover (entidades, internal linking, JSON-LD).
- **Fase 7 (sem 9):** automatizaciones + scheduler + bandeja editorial completa.
- **Fase 8 (sem 10):** feedback loop con GSC + ajuste de scoring.
- **Fase 9+:** evergreen refresh, modo live blog, multi-medio onboarding.

Antes de empezar una fase nueva, leer `docs/plan.md` y la sección correspondiente
para confirmar criterios de aceptación.

### 10.2 Añadir un nuevo agente del pipeline

1. Definir contrato I/O en `docs/agents/<nombre>.md`.
2. Crear `workers/src/pipeline/nodes/<nombre>.py` con la función pura.
3. Registrar en `graph.py` con sus edges.
4. Crear fixtures en `tests/fixtures/<nombre>/`.
5. Tests unitarios + un test de integración con LLM mockeado.
6. Documentar el prompt usado en `docs/prompts/<nombre>.md` con versión.

### 10.3 Añadir un nuevo CMS adapter

1. Implementar interfaz `CMSAdapter` de `workers/src/cms_adapters/base.py`.
   Métodos requeridos: `publish`, `update`, `delete`, `get_categories`,
   `get_tags`, `upload_media`.
2. Tests con mock del CMS y, si es posible, una instancia de staging real.
3. Documentar el método de autenticación en `docs/cms-adapters/<nombre>.md`.
4. Añadir al enum `cms_tipo` en migración.

### 10.4 Añadir un nuevo medio (tenant)

1. Superadmin crea entrada en `medios`.
2. Configura `cms_config` con credenciales (form en dashboard, no archivo).
3. Asocia usuarios via `usuarios_medios`.
4. Carga (opcional) catálogo de entidades específicas en `entidades_catalogo`.
5. Configura `scoring_pesos` por categoría con valores default.
6. Onboarding de redactores: cada uno pega sus ejemplos.

### 10.5 Workflow con Claude Code

Cuando trabajes en este repo con Claude Code:

1. **Siempre leer `docs/plan.md`** al inicio de una nueva sesión grande, para
   ubicar la fase actual.
2. **Antes de tocar un nodo del pipeline**, leer `docs/agents/<nombre>.md`.
3. **Antes de añadir migración**, ejecutar `make db-status` para ver estado.
4. **Cambios en prompts** requieren bump de versión en `docs/prompts/` y
   nota en el commit.
5. **Cambios en políticas (sección 6 de este archivo)** requieren PR aparte
   con doble revisión humana. Nunca relajar policies sin discusión explícita.

---

## 11. Definition of Done

Una feature está hecha cuando:

- [ ] Pasa todos los tests unitarios y de integración relevantes.
- [ ] Tiene documentación actualizada (`docs/`).
- [ ] Logs estructurados con `medio_id`, `run_id` si aplica.
- [ ] Métricas relevantes expuestas (OTel).
- [ ] Errores manejados explícitamente, no swallowing.
- [ ] Si toca BD, migración revisada y rollback documentado.
- [ ] Si toca prompts, versión incrementada y diff documentado.
- [ ] Si afecta a multi-tenant, verificado el RLS con test específico.
- [ ] Si genera contenido publicable, valida políticas de §6.
- [ ] Probado en dev con datos realistas (no solo synthetic).

---

## 12. Comandos de uso frecuente

```bash
# Levantar todo en dev
docker compose up -d

# Aplicar migraciones
make db-migrate

# Sembrar datos de dev (medios de ejemplo, entidades Aragón)
make db-seed

# Lanzar workers
make workers-up

# Lanzar dashboard
cd dashboard && pnpm dev

# Lanzar API
cd api && uv run uvicorn src.main:app --reload

# Tests
make test                 # todos los tests no-live
make test-live            # incluye tests con LLM real (cuesta dinero)

# Lint + format
make lint
make format

# Generar tipos compartidos (Pydantic → TS) si aplica
make typegen

# Inspeccionar cola
open http://localhost:3001  # bull-board

# Ver logs estructurados
docker compose logs -f workers | jq
```

---

## 13. Referencias internas

- `docs/plan.md` — roadmap completo y criterios de aceptación por fase.
- `docs/image-policy.md` — política de imagen detallada con ejemplos.
- `docs/agents/*.md` — especificación I/O y prompts de cada agente.
- `docs/cms-adapters/*.md` — cómo escribir adapters de CMS.
- `docs/style-guides-format.md` — estructura del markdown del style guide.
- `docs/prompts/*.md` — versionado de prompts.
- `docs/runbooks/*.md` — procedimientos de ops y troubleshooting.

---

## 14. Anti-patrones a evitar

Cosas que NO queremos en este código y por qué.

- **God-prompts.** No metas todo en un único prompt mega-largo. El pipeline
  está descompuesto en agentes precisamente para evitarlo. Si una tarea no
  cabe en un prompt limpio, decomponerla.
- **State en variables globales.** Todo el estado del pipeline vive en
  `PipelineState` y se persiste en `run_steps`. No hay globals.
- **Reintentos sin backoff.** Cualquier llamada a LLM o API externa usa el
  helper `with_retry` con backoff exponencial y jitter.
- **Hardcoded prompts en español dentro de strings Python.** Los prompts
  viven en `workers/src/pipeline/prompts/*.md` y se cargan con Jinja2.
- **Filtros de fuentes hardcoded en código.** La blacklist vive en
  `db/seeds/blacklist_dominios.txt` y se carga a una tabla. Modificable sin
  redeploy.
- **Async fake.** Si una función no hace I/O, no la marques `async`.
- **Suprimir excepciones genéricas.** `except Exception: pass` está prohibido.
  Captura específicas y loguea con contexto.
- **Dependencias innecesarias en el frontend.** No instalar libs grandes
  (moment, lodash) si Date nativo o utilidades pequeñas hacen el trabajo.

---

## 15. Estado del proyecto

- **Versión:** 0.0.1 (bootstrap)
- **Última actualización de este archivo:** ver `git log CLAUDE.md`
- **Owner técnico:** Dani Moreno (BirdCom)
- **Tenants iniciales:** Hoy Aragón, Diario de Huesca, Sports Aragón
- **Stack confirmado en sección 2.** Cualquier cambio mayor requiere actualizar
  esta sección antes del PR.

---

**Nota final para Claude Code:** este archivo es la fuente de verdad de las
decisiones de arquitectura. Si una solicitud del usuario entra en conflicto
con algo aquí (política de imagen, multi-tenancy, stack), pregunta antes de
implementar. Si hay que cambiar una decisión arquitectónica, se cambia aquí
primero, en un PR explícito.
