-- ============================================================================
-- 003: Fase 2 — Detección de tendencias
--
-- Añade:
-- - perfiles_deteccion: cada medio define N perfiles temáticos.
-- - fuentes_configuradas: por perfil, N fuentes (detector + cron + config).
-- - presupuestos_api: cap mensual por servicio externo (X API en Fase 2).
-- - columnas en senales: paywall, perfil_id, fuente_id, embedding, url_origen, region.
--
-- Todas las tablas nuevas: ENABLE + FORCE RLS con tenancy estricta.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Perfiles de detección
-- ---------------------------------------------------------------------------
CREATE TABLE perfiles_deteccion (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id              UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  nombre                TEXT NOT NULL,
  descripcion           TEXT,
  pais                  TEXT NOT NULL DEFAULT 'ES',
  idiomas               TEXT[] NOT NULL DEFAULT ARRAY['es']::TEXT[],
  keywords_obligatorias TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  keywords_negativas    TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  categoria_destino     TEXT NOT NULL,
  activo                BOOLEAN NOT NULL DEFAULT TRUE,
  ttl_dias              INT NOT NULL DEFAULT 90 CHECK (ttl_dias > 0),
  creado_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (medio_id, nombre)
);
COMMENT ON TABLE perfiles_deteccion IS
  'Perfiles temáticos por medio (politica_aragon, deportes, sucesos...). Cada perfil tiene sus fuentes.';

CREATE INDEX ix_perfiles_deteccion_medio ON perfiles_deteccion(medio_id);

-- ---------------------------------------------------------------------------
-- Fuentes configuradas
-- ---------------------------------------------------------------------------
CREATE TABLE fuentes_configuradas (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id              UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  perfil_id             UUID NOT NULL REFERENCES perfiles_deteccion(id) ON DELETE CASCADE,
  detector              TEXT NOT NULL CHECK (detector IN ('rss', 'gtrends', 'gdelt', 'x')),
  origen_url            TEXT,
  cron_expr             TEXT NOT NULL,
  config                JSONB NOT NULL DEFAULT '{}'::jsonb,
  usar_solo_como_senal  BOOLEAN NOT NULL DEFAULT FALSE,
  activo                BOOLEAN NOT NULL DEFAULT TRUE,
  creado_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ultima_ejec_at        TIMESTAMPTZ,
  ultima_ejec_estado    TEXT
);
COMMENT ON COLUMN fuentes_configuradas.usar_solo_como_senal IS
  'TRUE = la URL/dominio se usa para detectar tendencias pero NO se cita en redacción (paywall, copyright).';
COMMENT ON COLUMN fuentes_configuradas.config IS
  'Config específica del detector. RSS: {feeds: [...]}; GTrends: {geos: [{geo, peso}]}; X: {query, max_results}; GDELT: {filtro}.';

CREATE INDEX ix_fuentes_configuradas_perfil ON fuentes_configuradas(perfil_id);
CREATE INDEX ix_fuentes_configuradas_medio_detector ON fuentes_configuradas(medio_id, detector);
CREATE INDEX ix_fuentes_configuradas_activo ON fuentes_configuradas(activo) WHERE activo;

-- ---------------------------------------------------------------------------
-- Presupuestos de APIs externas (X, Voyage embeddings, etc.)
-- mes_ref es el primer día del mes para facilitar UPSERT mensual.
-- ---------------------------------------------------------------------------
CREATE TABLE presupuestos_api (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  medio_id              UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  servicio              TEXT NOT NULL,
  budget_mensual_eur    NUMERIC(10,4) NOT NULL CHECK (budget_mensual_eur > 0),
  gasto_mes_actual_eur  NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (gasto_mes_actual_eur >= 0),
  mes_ref               DATE NOT NULL,
  actualizado_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (medio_id, servicio, mes_ref)
);
COMMENT ON TABLE presupuestos_api IS
  'Hard cap mensual de gasto por (medio, servicio). El UPDATE atómico con RETURNING aplica el cap.';

-- ---------------------------------------------------------------------------
-- Extensiones de senales
-- ---------------------------------------------------------------------------
ALTER TABLE senales ADD COLUMN paywall    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE senales ADD COLUMN perfil_id  UUID REFERENCES perfiles_deteccion(id) ON DELETE SET NULL;
ALTER TABLE senales ADD COLUMN fuente_id  UUID REFERENCES fuentes_configuradas(id) ON DELETE SET NULL;
ALTER TABLE senales ADD COLUMN embedding  vector(1024);
ALTER TABLE senales ADD COLUMN url_origen TEXT;
ALTER TABLE senales ADD COLUMN region     TEXT;

CREATE INDEX ix_senales_embedding ON senales USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ix_senales_medio_origen ON senales(medio_id, origen);
CREATE INDEX ix_senales_perfil ON senales(perfil_id);
-- Para queries del dashboard "top N no expiradas": el filtro `expira_at > NOW()`
-- va en el WHERE de la query, no en el índice (predicados de índice requieren
-- funciones IMMUTABLE y NOW() es STABLE). Los índices de score y de expira_at
-- por separado cubren razonablemente el plan.
CREATE INDEX ix_senales_expira ON senales(medio_id, expira_at DESC);

-- ---------------------------------------------------------------------------
-- RLS para tablas nuevas
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY[
    'perfiles_deteccion', 'fuentes_configuradas', 'presupuestos_api'
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

-- Grants al rol grupo
GRANT SELECT, INSERT, UPDATE, DELETE ON
  perfiles_deteccion, fuentes_configuradas, presupuestos_api
TO redactia_app;

COMMIT;
