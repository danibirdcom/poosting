-- ============================================================================
-- 006: auditoria_humano + ampliar estado 'archivado' en drafts
--
-- Cambios:
-- 1. Añade 'archivado' al CHECK del campo drafts.estado.
-- 2. Crea tabla auditoria_humano: registro de acciones humanas sobre drafts
--    (aprobar/rechazar/editar/archivar). Trazabilidad GDPR + auditoría.
-- 3. RLS estándar multi-tenant.
-- 4. Índices: por draft_id (vista historial) y (medio_id, creado_at)
--    para vista cronológica.
--
-- Notas:
-- - usuario_id NULL en Fase 4 PR1 (sin auth todavía). En PR2 se rellena
--   con UUID del usuario logueado.
-- - diff_resumen JSONB guarda before/after de campos editados para
--   reconstruir historial.
-- - workers NO escribe aquí; es solo el rol redactia_web (grants en 007).
-- ============================================================================

BEGIN;

-- 1. Ampliar el CHECK de drafts.estado para incluir 'archivado'.
--    El estado representa el ciclo de vida desde la perspectiva editorial:
--    borrador → (aprobado | rechazado) → publicado | archivado.
ALTER TABLE drafts DROP CONSTRAINT IF EXISTS drafts_estado_check;
ALTER TABLE drafts ADD CONSTRAINT drafts_estado_check
  CHECK (estado IN (
    'borrador', 'aprobado', 'publicado', 'rechazado', 'programado', 'archivado'
  ));

-- 2. Tabla de auditoría de acciones humanas.
CREATE TABLE auditoria_humano (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id     UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  medio_id     UUID NOT NULL REFERENCES medios(id) ON DELETE CASCADE,
  usuario_id   UUID REFERENCES usuarios(id) ON DELETE SET NULL,
  accion       TEXT NOT NULL CHECK (accion IN (
                 'aprobado', 'rechazado', 'editado', 'archivado'
               )),
  notas        TEXT,
  diff_resumen JSONB,
  creado_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE auditoria_humano IS
  'Registro de acciones humanas sobre drafts. Lo escribe la UI cuando el '
  'editor aprueba/rechaza/edita/archiva. Trazabilidad GDPR + auditoría. '
  'workers nunca escribe aquí.';

CREATE INDEX ix_auditoria_humano_draft ON auditoria_humano(draft_id);
CREATE INDEX ix_auditoria_humano_medio_fecha
  ON auditoria_humano(medio_id, creado_at DESC);

-- 3. RLS estándar multi-tenant (mismo patrón que el resto de tablas con
--    medio_id, ver §4 de CLAUDE.md).
ALTER TABLE auditoria_humano ENABLE ROW LEVEL SECURITY;
ALTER TABLE auditoria_humano FORCE ROW LEVEL SECURITY;

CREATE POLICY tenancy_auditoria_humano ON auditoria_humano
  USING (medio_id = app_current_medio())
  WITH CHECK (medio_id = app_current_medio());

-- Nota: GRANTs al rol redactia_web se hacen en migración 007 (que crea el
-- rol). Aquí solo creamos la tabla y la policy.

COMMIT;
