-- Catálogo inicial de entidades para tenants aragoneses (medio_id NULL = global).
-- Cargar tras 001_initial.sql.

BEGIN;

INSERT INTO entidades_catalogo (medio_id, tipo, nombre_canonico, aliases, wikidata_id, contexto_md)
VALUES
  -- Personas (cargo + nombre actualizado a 2026)
  (NULL, 'persona', 'Jorge Azcón', ARRAY['Azcón', 'Jorge Antonio Azcón Navarro'], 'Q5969632',
    'Presidente del Gobierno de Aragón desde agosto de 2023. Anteriormente alcalde de Zaragoza (2019-2023). PP.'),
  (NULL, 'persona', 'Natalia Chueca', ARRAY['Chueca'], NULL,
    'Alcaldesa de Zaragoza desde junio de 2023. PP.'),
  (NULL, 'persona', 'Lorena Orduna', ARRAY['Orduna'], NULL,
    'Alcaldesa de Huesca desde junio de 2023. PP.'),
  (NULL, 'persona', 'Emma Buj', ARRAY['Buj'], NULL,
    'Alcaldesa de Teruel desde 2011. PP.'),

  -- Lugares
  (NULL, 'lugar', 'Zaragoza', ARRAY['Saraqusta'], 'Q10305',
    'Capital de Aragón y de la provincia de Zaragoza. ~675.000 habitantes.'),
  (NULL, 'lugar', 'Huesca', ARRAY['Uesca'], 'Q11959',
    'Capital de la provincia de Huesca. ~53.000 habitantes.'),
  (NULL, 'lugar', 'Teruel', ARRAY[]::TEXT[], 'Q14336',
    'Capital de la provincia de Teruel. ~36.000 habitantes.'),
  (NULL, 'lugar', 'Jaca', ARRAY[]::TEXT[], 'Q193552',
    'Municipio del Alto Aragón, cabecera comarcal de la Jacetania.'),
  (NULL, 'lugar', 'Calatayud', ARRAY[]::TEXT[], 'Q204862',
    'Municipio de la provincia de Zaragoza, cabecera de la Comunidad de Calatayud.'),
  (NULL, 'lugar', 'Alcañiz', ARRAY[]::TEXT[], 'Q1377396',
    'Municipio de la provincia de Teruel, cabecera del Bajo Aragón.'),

  -- Organizaciones
  (NULL, 'organizacion', 'Gobierno de Aragón', ARRAY['DGA', 'Diputación General de Aragón'], 'Q3032282',
    'Institución de autogobierno de la Comunidad Autónoma de Aragón.'),
  (NULL, 'organizacion', 'Real Zaragoza', ARRAY['Zaragoza', 'el Real'], 'Q7993',
    'Club de fútbol de Zaragoza fundado en 1932.'),
  (NULL, 'organizacion', 'SD Huesca', ARRAY['Sociedad Deportiva Huesca'], 'Q1133017',
    'Club de fútbol de Huesca fundado en 1960.'),
  (NULL, 'organizacion', 'CAI Zaragoza', ARRAY['Casademont Zaragoza'], NULL,
    'Club de baloncesto de Zaragoza, ACB.'),

  -- Eventos
  (NULL, 'evento', 'Fiestas del Pilar', ARRAY['Pilares'], 'Q2510378',
    'Fiestas mayores de Zaragoza en honor a la Virgen del Pilar, en torno al 12 de octubre.'),
  (NULL, 'evento', 'Cincomarzada', ARRAY[]::TEXT[], NULL,
    'Celebración popular zaragozana el 5 de marzo.'),
  (NULL, 'evento', 'Vuelta a Aragón', ARRAY[]::TEXT[], NULL,
    'Carrera ciclista por etapas en territorio aragonés.'),
  (NULL, 'evento', 'Aragón Open Future', ARRAY[]::TEXT[], NULL,
    'Programa de innovación y emprendimiento de Telefónica y Gobierno de Aragón.')
ON CONFLICT (medio_id, nombre_canonico) DO NOTHING;

COMMIT;
