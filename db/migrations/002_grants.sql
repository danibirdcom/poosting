-- ============================================================================
-- 002: Roles y grants para la app
--
-- Crea el rol grupo ``redactia_app`` con privilegios CRUD sobre todas las
-- tablas. Cada entorno (dev, ci, prod) debe conceder pertenencia a este rol
-- a su usuario de aplicación concreto:
--
--   GRANT redactia_app TO redactia_app_ci;
--   GRANT redactia_app TO redactia_app_dev;
--
-- Esto se hace fuera de la migración para que el SQL sea portable: la
-- migración no conoce los nombres de usuario de cada entorno.
--
-- Por qué un rol grupo en lugar de grants directos: si mañana añadimos
-- redactia_app_prod basta con `GRANT redactia_app TO redactia_app_prod`,
-- sin tocar las tablas.
-- ============================================================================

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'redactia_app') THEN
    CREATE ROLE redactia_app NOLOGIN;
  END IF;
END $$;

-- Esquema
GRANT USAGE ON SCHEMA public TO redactia_app;

-- Tablas multi-tenant: CRUD completo (RLS hace el filtrado por fila)
GRANT SELECT, INSERT, UPDATE, DELETE ON
  redactores, estilos_redactor, ejemplos_redactor,
  variantes_tematicas_redactor, correcciones_redactor,
  senales, automatizaciones, runs, run_steps, fuentes_run,
  drafts, imagenes_articulo, gsc_metricas, scoring_pesos,
  licencias_fuentes, entidades_catalogo
TO redactia_app;

-- Tablas globales / no multi-tenant
GRANT SELECT, INSERT, UPDATE, DELETE ON medios TO redactia_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON usuarios TO redactia_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON usuarios_medios TO redactia_app;
GRANT SELECT ON blacklist_dominios TO redactia_app;

-- Funciones expuestas
GRANT EXECUTE ON FUNCTION app_current_medio() TO redactia_app;

-- Quitar privilegios por defecto de PUBLIC sobre tablas creadas en este
-- esquema (defensa en profundidad: si alguien crea un usuario sin grant
-- explícito, no debe poder leer nada).
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

COMMIT;
