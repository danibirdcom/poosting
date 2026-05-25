-- ============================================================================
-- 007: Rol redactia_web para la UI Next.js (Fase 4 PR1)
--
-- Patrón: igual que `redactia_app` (migración 002) — rol GRUPO sin login.
-- Cada entorno (dev, ci, prod) crea su propio usuario login y le concede
-- pertenencia:
--
--   CREATE ROLE redactia_web_dev LOGIN PASSWORD '...';
--   GRANT redactia_web TO redactia_web_dev;
--
-- Esto mantiene la migración portable: no contiene passwords ni nombres
-- de base de datos. Ver setup en CLAUDE.md §10.
--
-- Permisos:
-- - SELECT en tablas de lectura para la bandeja, editor y trazabilidad.
-- - UPDATE acotado en drafts (solo campos editables por humano).
-- - INSERT + SELECT en auditoria_humano (registrar acciones).
-- - EXECUTE en app_current_medio() para que RLS funcione bajo este rol.
--
-- defense-in-depth: workers usa `redactia_app` (CRUD), web usa
-- `redactia_web` (lectura + update acotado). RLS sigue activa bajo ambos.
-- ============================================================================

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'redactia_web') THEN
    CREATE ROLE redactia_web NOLOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO redactia_web;

-- SELECT en tablas de lectura.
-- Nota: NO incluimos `usuarios` ni `usuarios_medios` aquí (PR2 cuando
-- entre NextAuth). En PR1 web es read-only de drafts/runs.
GRANT SELECT ON
  drafts, runs, run_steps, senales, redactores, medios,
  entidades_catalogo, imagenes_articulo, draft_entidades,
  estilos_redactor, ejemplos_redactor, fuentes_run,
  variantes_tematicas_redactor, correcciones_redactor,
  automatizaciones, gsc_metricas, scoring_pesos, licencias_fuentes
TO redactia_web;

-- UPDATE acotado en drafts: solo los campos que un editor humano puede
-- modificar. NO toca medio_id, run_id, embedding, creado_at, etc.
-- Nota: la columna `updated_at` NO existe en drafts (verificado contra
-- el schema real). Si en el futuro se añade, ampliar este GRANT.
GRANT UPDATE (
  titulo, meta_title, meta_descr, slug, cuerpo_md, cuerpo_html,
  estado, motivo_rechazo, schema_jsonld, imagen_destacada_id,
  programado_para
) ON drafts TO redactia_web;

-- INSERT + SELECT en auditoria_humano (la web es la única que escribe ahí).
GRANT SELECT, INSERT ON auditoria_humano TO redactia_web;

-- Función para RLS.
GRANT EXECUTE ON FUNCTION app_current_medio() TO redactia_web;

COMMIT;
