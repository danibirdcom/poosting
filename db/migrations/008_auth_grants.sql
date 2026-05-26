-- ============================================================================
-- 008: GRANTs adicionales para auth (Fase 4 PR2)
--
-- En PR2 entra NextAuth. El Credentials Provider necesita:
--   - SELECT en usuarios (lookup por email + lectura de password_hash).
--   - SELECT en usuarios_medios (decidir qué medio_id activa la sesión).
--   - UPDATE acotado en usuarios(password_hash) para futuros endpoints
--     de cambio de contraseña.
--
-- Ninguna de estas tablas tiene RLS (son globales / fuente de verdad de
-- membresía), por lo que basta con los GRANT — el authorize() puede leer
-- directo sin setear app.medio_actual.
-- ============================================================================

BEGIN;

GRANT SELECT ON usuarios TO redactia_web;
GRANT SELECT ON usuarios_medios TO redactia_web;
GRANT UPDATE (password_hash) ON usuarios TO redactia_web;

COMMIT;
