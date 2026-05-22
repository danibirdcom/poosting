-- ============================================================================
-- Redactia — Migración inicial
-- Define el esquema completo descrito en CLAUDE.md §4.
-- Idempotente donde es posible (CREATE EXTENSION IF NOT EXISTS, etc).
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Extensiones
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid, encrypt
CREATE EXTENSION IF NOT EXISTS "vector";     -- pgvector para embeddings
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- búsqueda por trigramas

-- ---------------------------------------------------------------------------
-- Helper: setting de contexto multi-tenant
-- Cada request de la aplicación debe ejecutar:
--   SET LOCAL app.medio_actual = '<uuid>';
-- antes de cualquier query. Las RLS policies leen ese setting.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app_current_medio() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('app.medio_actual', true), '')::uuid;
$$ LANGUAGE SQL STABLE;

-- ===========================================================================
-- 4.1 Tenancy y usuarios
-- ===========================================================================

CREATE TABLE medios (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug            TEXT UNIQUE NOT NULL,
  nombre          TEXT NOT NULL,
  cms_tipo        TEXT NOT NULL CHECK (cms_tipo IN ('wordpress', 'opendemas', 'custom')),
  cms_config      JSONB NOT NULL DEFAULT '{}'::jsonb,  -- cifrado en la app antes de guardar
  style_guide_md  TEXT,
  activo          BOOLEAN NOT NULL DEFAULT TRUE,
  creado_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE medios IS 'Tenants del sistema. Un medio = un periódico digital.';
COMMENT ON COLUMN medios.cms_config IS 'Credenciales del CMS cifradas en la app antes de persistir.';

CREATE TABLE usuarios (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email           TEXT UNIQUE NOT NULL,
  nombre          TEXT NOT NULL,
  password_hash   TEXT NOT NULL,
  rol_global      TEXT CHECK (rol_global IS NULL OR rol_global IN ('superadmin')),
  creado_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE usuarios_medios (
  usuario_id      UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  rol             TEXT NOT NULL CHECK (rol IN ('editor_jefe', 'redactor', 'colaborador')),
  PRIMARY KEY (usuario_id, medio_id)
);
CREATE INDEX ix_usuarios_medios_medio ON usuarios_medios(medio_id);

-- ===========================================================================
-- 4.2 Redactores y estilo
-- ===========================================================================

CREATE TABLE redactores (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  usuario_id      UUID REFERENCES usuarios(id) ON DELETE SET NULL,
  nombre_publico  TEXT NOT NULL,
  activo          BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX ix_redactores_medio ON redactores(medio_id);

CREATE TABLE estilos_redactor (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  redactor_id     UUID NOT NULL REFERENCES redactores(id) ON DELETE CASCADE,
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  version         INT NOT NULL,
  guia_estilo_md  TEXT NOT NULL,
  metricas        JSONB NOT NULL DEFAULT '{}'::jsonb,
  generado_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  activo          BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (redactor_id, version)
);
-- Solo una versión activa por redactor
CREATE UNIQUE INDEX ux_estilos_redactor_activo
  ON estilos_redactor(redactor_id) WHERE activo;

CREATE TABLE ejemplos_redactor (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  redactor_id     UUID NOT NULL REFERENCES redactores(id) ON DELETE CASCADE,
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  texto_completo  TEXT NOT NULL,
  titulo          TEXT,
  url_origen      TEXT,
  fecha_pub       DATE,
  embedding       vector(1024),
  pegado_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_ejemplos_redactor_redactor ON ejemplos_redactor(redactor_id);
CREATE INDEX ix_ejemplos_redactor_embedding
  ON ejemplos_redactor USING hnsw (embedding vector_cosine_ops);

CREATE TABLE variantes_tematicas_redactor (
  redactor_id     UUID NOT NULL REFERENCES redactores(id) ON DELETE CASCADE,
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  tema_codigo     TEXT NOT NULL,
  ajustes_md      TEXT NOT NULL,
  PRIMARY KEY (redactor_id, tema_codigo)
);

CREATE TABLE correcciones_redactor (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id        UUID NOT NULL,   -- FK añadida abajo, después de crear drafts
  redactor_id     UUID NOT NULL REFERENCES redactores(id) ON DELETE CASCADE,
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  diff            JSONB NOT NULL,
  categoria       TEXT NOT NULL CHECK (categoria IN ('tono', 'estructura', 'vocab', 'factual')),
  creado_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_correcciones_redactor_redactor ON correcciones_redactor(redactor_id);

-- ===========================================================================
-- 4.3 Señales y fuentes
-- ===========================================================================

CREATE TABLE senales (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  origen          TEXT NOT NULL CHECK (origen IN ('gtrends', 'x', 'gdelt', 'gsc', 'rss')),
  termino         TEXT NOT NULL,
  pais            TEXT,
  categoria       TEXT,
  score           NUMERIC(6,3) NOT NULL,
  velocidad       NUMERIC,
  volumen         INT,
  metadatos       JSONB,
  detectado_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expira_at       TIMESTAMPTZ
);
CREATE INDEX ix_senales_medio_score ON senales(medio_id, score DESC);
CREATE INDEX ix_senales_detectado ON senales(detectado_at DESC);

-- ===========================================================================
-- 4.4 Runs, drafts, fuentes_run e imágenes
-- ===========================================================================

CREATE TABLE automatizaciones (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  nombre          TEXT NOT NULL,
  tipo            TEXT NOT NULL CHECK (tipo IN ('senales', 'tematica')),
  cron_expr       TEXT NOT NULL,
  config          JSONB NOT NULL,
  activo          BOOLEAN NOT NULL DEFAULT TRUE,
  creado_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ultima_ejec_at  TIMESTAMPTZ
);
CREATE INDEX ix_automatizaciones_medio ON automatizaciones(medio_id);

CREATE TABLE runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  redactor_id     UUID REFERENCES redactores(id) ON DELETE SET NULL,
  trigger_tipo    TEXT NOT NULL CHECK (trigger_tipo IN ('manual', 'automatizacion', 'evergreen')),
  trigger_id      UUID REFERENCES automatizaciones(id) ON DELETE SET NULL,
  senal_id        UUID REFERENCES senales(id) ON DELETE SET NULL,
  tema_input      TEXT,
  categoria       TEXT,
  estado          TEXT NOT NULL CHECK (estado IN ('pendiente', 'ejecutando', 'completado', 'fallido')),
  iniciado_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finalizado_at   TIMESTAMPTZ,
  coste_eur       NUMERIC(8,4)
);
CREATE INDEX ix_runs_medio_estado ON runs(medio_id, estado);
CREATE INDEX ix_runs_iniciado ON runs(iniciado_at DESC);

CREATE TABLE run_steps (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  step_nombre     TEXT NOT NULL CHECK (step_nombre IN ('detect', 'research', 'write', 'review', 'enrich', 'publish')),
  estado          TEXT NOT NULL CHECK (estado IN ('pendiente', 'ejecutando', 'completado', 'fallido')),
  input           JSONB,
  output          JSONB,
  prompt_usado    TEXT,
  modelo          TEXT,
  tokens_in       INT,
  tokens_out      INT,
  duracion_ms     INT,
  error           TEXT,
  iniciado_at     TIMESTAMPTZ,
  finalizado_at   TIMESTAMPTZ,
  UNIQUE (run_id, step_nombre)
);
CREATE INDEX ix_run_steps_run ON run_steps(run_id);

CREATE TABLE fuentes_run (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id              UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  medio_id            UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  url                 TEXT NOT NULL,
  titulo              TEXT,
  publicado_at        TIMESTAMPTZ,
  autoridad_score     NUMERIC,
  contenido_md        TEXT,
  citado_en_articulo  BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX ix_fuentes_run_run ON fuentes_run(run_id);

CREATE TABLE drafts (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  medio_id              UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  titulo                TEXT NOT NULL,
  meta_title            TEXT,
  meta_descr            TEXT,
  slug                  TEXT,
  cuerpo_md             TEXT NOT NULL,
  cuerpo_html           TEXT,
  entidades             JSONB,
  enlaces_internos      JSONB,
  imagen_destacada_id   UUID,  -- FK añadida abajo
  schema_jsonld         JSONB,
  estado                TEXT NOT NULL CHECK (estado IN (
                          'borrador', 'aprobado', 'publicado', 'rechazado', 'programado'
                        )),
  motivo_rechazo        TEXT,
  similitud_max         NUMERIC,
  embedding             vector(1024),
  creado_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  programado_para       TIMESTAMPTZ,
  publicado_at          TIMESTAMPTZ,
  cms_url               TEXT,
  cms_id_externo        TEXT
);
CREATE INDEX ix_drafts_medio_estado ON drafts(medio_id, estado);
CREATE INDEX ix_drafts_creado ON drafts(creado_at DESC);
CREATE INDEX ix_drafts_embedding
  ON drafts USING hnsw (embedding vector_cosine_ops);

-- Ya podemos cerrar la FK de correcciones_redactor → drafts
ALTER TABLE correcciones_redactor
  ADD CONSTRAINT fk_correcciones_redactor_draft
  FOREIGN KEY (draft_id) REFERENCES drafts(id) ON DELETE CASCADE;

CREATE TABLE imagenes_articulo (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id                UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  medio_id                UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  storage_path            TEXT NOT NULL,
  url_publica             TEXT,
  fuente                  TEXT NOT NULL CHECK (fuente IN (
                            'banco_licencia', 'nano_banana_2', 'gpt_image_2', 'manual'
                          )),
  prompt_usado            TEXT,
  modelo_version          TEXT,
  c2pa_metadata           JSONB,
  synthid_present         BOOLEAN,
  alt_text                TEXT NOT NULL,
  pie_foto                TEXT NOT NULL,
  declaracion_ia_visible  BOOLEAN NOT NULL,
  banco_licencia_id       TEXT,
  banco_licencia_tipo     TEXT CHECK (banco_licencia_tipo IS NULL OR banco_licencia_tipo IN (
                            'pexels', 'unsplash', 'pixabay', 'efe', 'europa_press'
                          )),
  creado_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_imagenes_articulo_draft ON imagenes_articulo(draft_id);

ALTER TABLE drafts
  ADD CONSTRAINT fk_drafts_imagen_destacada
  FOREIGN KEY (imagen_destacada_id) REFERENCES imagenes_articulo(id) ON DELETE SET NULL;

-- ===========================================================================
-- 4.5 Feedback (GSC) y scoring
-- ===========================================================================

CREATE TABLE gsc_metricas (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  draft_id        UUID REFERENCES drafts(id) ON DELETE SET NULL,
  url             TEXT NOT NULL,
  fecha           DATE NOT NULL,
  impresiones     INT,
  clicks          INT,
  ctr             NUMERIC,
  posicion        NUMERIC,
  fuente          TEXT NOT NULL CHECK (fuente IN ('search', 'discover')),
  capturado_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (draft_id, fecha, fuente)
);
CREATE INDEX ix_gsc_metricas_medio_fecha ON gsc_metricas(medio_id, fecha DESC);

CREATE TABLE scoring_pesos (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  categoria       TEXT NOT NULL,
  peso_velocidad  NUMERIC NOT NULL DEFAULT 1.0,
  peso_volumen    NUMERIC NOT NULL DEFAULT 1.0,
  peso_freshness  NUMERIC NOT NULL DEFAULT 1.0,
  peso_intent     NUMERIC NOT NULL DEFAULT 1.0,
  actualizado_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (medio_id, categoria)
);

-- ===========================================================================
-- 4.6 Catálogo de entidades
-- ===========================================================================

CREATE TABLE entidades_catalogo (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id        UUID REFERENCES medios(id) ON DELETE CASCADE,  -- NULL = global
  tipo            TEXT NOT NULL CHECK (tipo IN ('persona', 'organizacion', 'lugar', 'evento')),
  nombre_canonico TEXT NOT NULL,
  aliases         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  wikidata_id     TEXT,
  contexto_md     TEXT,
  embedding       vector(1024),
  activo          BOOLEAN NOT NULL DEFAULT TRUE,
  creado_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_entidades_catalogo_medio ON entidades_catalogo(medio_id);
CREATE INDEX ix_entidades_catalogo_nombre_trgm
  ON entidades_catalogo USING gin (nombre_canonico gin_trgm_ops);
CREATE INDEX ix_entidades_catalogo_embedding
  ON entidades_catalogo USING hnsw (embedding vector_cosine_ops);

-- ===========================================================================
-- Blacklist de dominios
-- ===========================================================================

CREATE TABLE blacklist_dominios (
  dominio         TEXT PRIMARY KEY,
  razon           TEXT NOT NULL,
  añadido_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===========================================================================
-- Licencias de fuentes con paywall
-- ===========================================================================

CREATE TABLE licencias_fuentes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id        UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  dominio         TEXT NOT NULL,
  tipo_licencia   TEXT NOT NULL,
  notas           TEXT,
  activo          BOOLEAN NOT NULL DEFAULT TRUE,
  creado_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (medio_id, dominio)
);

-- ===========================================================================
-- Row Level Security
--
-- Política estándar para tablas multi-tenant (todas las que tienen columna
-- medio_id NOT NULL): SELECT/UPDATE/DELETE solo ven filas del medio actual,
-- INSERT/UPDATE rechaza filas con medio_id ajeno.
--
-- - FORCE ROW LEVEL SECURITY: aplica también al owner (redactia_admin).
--   Sin FORCE, el owner saltaría todas las policies.
-- - USING + WITH CHECK: sin WITH CHECK los INSERT no se filtran y la app
--   podría escribir cross-tenant. Crítico.
-- - current_setting('app.medio_actual', true): el segundo arg `true` evita
--   error si el setting no está; devuelve NULL → la comparación es NULL →
--   no aprueba (deny-by-default).
--
-- Tablas fuera de este RLS:
--   - usuarios: no es multi-tenant (un usuario puede pertenecer a varios medios).
--   - usuarios_medios: es la fuente de verdad de membresía; consultada por
--     get_request_context antes de fijar el contexto.
--   - blacklist_dominios: catálogo global de solo lectura.
-- ===========================================================================

-- Tablas multi-tenant con medio_id NOT NULL. Policy estándar.
DO $$
DECLARE
  t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY[
    'redactores', 'estilos_redactor', 'ejemplos_redactor',
    'variantes_tematicas_redactor', 'correcciones_redactor',
    'senales', 'automatizaciones', 'runs', 'run_steps', 'fuentes_run',
    'drafts', 'imagenes_articulo', 'gsc_metricas', 'scoring_pesos',
    'licencias_fuentes'
  ]) LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenancy_%1$I ON %1$I '
      'USING (medio_id = app_current_medio()) '
      'WITH CHECK (medio_id = app_current_medio())',
      t
    );
  END LOOP;
END $$;

-- medios: no es estrictamente multi-tenant (el "tenant" ES esta fila). Pero
-- queremos que con app_current_medio fijado, la sesión solo vea su propio
-- medio. Con setting NULL (flujo de login + tareas de admin), permitimos
-- ver/insertar — el grant restringe quién puede hacer qué.
ALTER TABLE medios ENABLE ROW LEVEL SECURITY;
ALTER TABLE medios FORCE ROW LEVEL SECURITY;
CREATE POLICY tenancy_medios ON medios
  USING (id = app_current_medio() OR app_current_medio() IS NULL)
  WITH CHECK (id = app_current_medio() OR app_current_medio() IS NULL);

-- entidades_catalogo: filas globales (medio_id IS NULL) son visibles por
-- todos los tenants. Solo se pueden insertar/modificar filas del tenant
-- propio; la creación de globales requiere admin sin contexto.
ALTER TABLE entidades_catalogo ENABLE ROW LEVEL SECURITY;
ALTER TABLE entidades_catalogo FORCE ROW LEVEL SECURITY;
CREATE POLICY tenancy_entidades_catalogo ON entidades_catalogo
  USING (medio_id IS NULL OR medio_id = app_current_medio())
  WITH CHECK (
    (medio_id IS NULL AND app_current_medio() IS NULL)
    OR medio_id = app_current_medio()
  );

COMMIT;
