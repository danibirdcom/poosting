-- ============================================================================
-- 004: Fase 3 — Pipeline multiagente de redacción
--
-- Cambios:
-- 1. UNIQUE en entidades_catalogo (medio_id, nombre_canonico) con NULLS NOT
--    DISTINCT para que las entradas globales (medio_id IS NULL) se traten como
--    iguales en el conflict target.
-- 2. Backfill de entidades adicionales (idempotente con ON CONFLICT).
-- 3. Denormaliza drafts.senal_id con trigger BEFORE INSERT/UPDATE que lo
--    sincroniza desde runs.senal_id. Acelera el check de canibalización
--    exacta sin JOIN.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. UNIQUE en entidades_catalogo
-- ---------------------------------------------------------------------------
-- NULLS NOT DISTINCT es Postgres 15+: hace que dos NULL en medio_id se
-- consideren iguales para fines de UNIQUE. Sin esto, podríamos insertar
-- la misma entidad global ('Azcón', medio_id NULL) varias veces.
ALTER TABLE entidades_catalogo
  ADD CONSTRAINT ux_entidades_catalogo_medio_nombre
  UNIQUE NULLS NOT DISTINCT (medio_id, nombre_canonico);

-- ---------------------------------------------------------------------------
-- 2. Entidades adicionales para Fase 3
-- Solapadas con seeds/entidades_aragon.sql (Fase 1) — el ON CONFLICT salta
-- duplicados. Mantengo aquí solo las que el spec de Fase 3 lista
-- explícitamente con sus contextos.
-- ---------------------------------------------------------------------------
INSERT INTO entidades_catalogo (medio_id, tipo, nombre_canonico, aliases, contexto_md)
VALUES
  (NULL, 'persona', 'Jorge Azcón', ARRAY['Azcón'],
    'Presidente del Gobierno de Aragón (PP) desde 2023.'),
  (NULL, 'persona', 'Natalia Chueca', ARRAY['Chueca'],
    'Alcaldesa de Zaragoza (PP) desde 2023.'),
  (NULL, 'organizacion', 'DGA', ARRAY['Diputación General de Aragón', 'Gobierno de Aragón'],
    'Ejecutivo de la Comunidad Autónoma de Aragón.'),
  (NULL, 'organizacion', 'Real Zaragoza', ARRAY['RZ'],
    'Equipo de fútbol con sede en Zaragoza, actualmente en LaLiga Hypermotion.'),
  (NULL, 'organizacion', 'SD Huesca', ARRAY['Huesca'],
    'Equipo de fútbol con sede en Huesca, actualmente en LaLiga Hypermotion.'),
  (NULL, 'lugar', 'Zaragoza', ARRAY['Zgz'],
    'Capital de Aragón.'),
  (NULL, 'lugar', 'Huesca', ARRAY[]::TEXT[],
    'Capital de la provincia de Huesca.'),
  (NULL, 'lugar', 'Teruel', ARRAY[]::TEXT[],
    'Capital de la provincia de Teruel.'),
  (NULL, 'evento', 'Fiestas del Pilar', ARRAY['Pilares'],
    'Fiestas patronales de Zaragoza, segunda quincena de octubre.')
ON CONFLICT (medio_id, nombre_canonico) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. drafts.senal_id denormalizado con trigger
-- ---------------------------------------------------------------------------
ALTER TABLE drafts
  ADD COLUMN senal_id UUID REFERENCES senales(id) ON DELETE SET NULL;

COMMENT ON COLUMN drafts.senal_id IS
  'Denormalizado desde runs.senal_id por trigger trg_sync_drafts_senal_id. '
  'Permite check de canibalización exacta sin JOIN.';

-- Backfill: drafts ya existentes (en staging puede haberlos de pruebas).
UPDATE drafts d
   SET senal_id = r.senal_id
  FROM runs r
 WHERE r.id = d.run_id
   AND d.senal_id IS NULL
   AND r.senal_id IS NOT NULL;

-- Trigger: sincroniza senal_id desde el run asociado en INSERT y cuando
-- run_id cambia (raro pero posible). NEW.senal_id solo se reescribe si
-- viene NULL — permite override explícito en código si hace falta.
CREATE OR REPLACE FUNCTION sync_drafts_senal_id() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.senal_id IS NULL AND NEW.run_id IS NOT NULL THEN
    SELECT senal_id INTO NEW.senal_id FROM runs WHERE id = NEW.run_id;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_sync_drafts_senal_id
BEFORE INSERT OR UPDATE OF run_id ON drafts
FOR EACH ROW
EXECUTE FUNCTION sync_drafts_senal_id();

-- Índice para la query de canibalización exacta: "¿hemos cubierto esta
-- señal en los últimos 30 días?". WHERE publicado_at IS NOT NULL excluye
-- drafts en bandeja.
CREATE INDEX ix_drafts_medio_senal_pub
  ON drafts(medio_id, senal_id, publicado_at)
  WHERE publicado_at IS NOT NULL;

COMMIT;
