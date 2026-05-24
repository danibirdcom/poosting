-- ============================================================================
-- 005: Tabla draft_entidades (linking N:N drafts ↔ entidades_catalogo)
--
-- Cambios:
-- 1. Tabla draft_entidades con FK a drafts y entidades_catalogo + medio_id
--    para RLS. Permite consultas tipo "¿qué drafts han mencionado a X?"
--    sin tener que escanear el JSONB de drafts.entidades.
-- 2. Índices: por (medio_id, entidad_id) — uso típico desde el dashboard
--    (vista de entidad → listado de drafts). Por (draft_id) — recuperación
--    inversa.
-- 3. RLS + FORCE + WITH CHECK por medio_id (estándar multi-tenant).
--
-- Nota: drafts.entidades (JSONB) NO se elimina. Se mantiene como historial
-- denormalizado para retrocompatibilidad con tests anteriores. La nueva
-- tabla es la fuente de verdad relacional.
-- ============================================================================

BEGIN;

CREATE TABLE draft_entidades (
  draft_id     UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  entidad_id   UUID NOT NULL REFERENCES entidades_catalogo(id) ON DELETE CASCADE,
  medio_id     UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  creado_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (draft_id, entidad_id)
);

COMMENT ON TABLE draft_entidades IS
  'Linking N:N entre drafts y entidades_catalogo. Lo escribe el nodo enrich '
  'desde state.entidades (con catalogo_id mapeado). drafts.entidades (JSONB) '
  'se mantiene como denormalizado para retrocompat.';

CREATE INDEX ix_draft_entidades_medio_entidad
  ON draft_entidades(medio_id, entidad_id);

CREATE INDEX ix_draft_entidades_draft
  ON draft_entidades(draft_id);

-- RLS estándar multi-tenant (mismo patrón que en 001_initial.sql).
ALTER TABLE draft_entidades ENABLE ROW LEVEL SECURITY;
ALTER TABLE draft_entidades FORCE ROW LEVEL SECURITY;

CREATE POLICY tenancy_draft_entidades ON draft_entidades
  USING (medio_id = app_current_medio())
  WITH CHECK (medio_id = app_current_medio());

GRANT SELECT, INSERT, DELETE ON draft_entidades TO redactia_app;

COMMIT;
