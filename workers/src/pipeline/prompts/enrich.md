# Prompt: enrich

Versión: 1.0.0 (PR B)

El nodo `enrich` es mayoritariamente programático (vector search, generación
de JSON-LD, OpenGraph, búsqueda Pexels). No usa LLM directamente; este
archivo documenta los criterios de los componentes para auditoría.

## Internal linking

- Vector search en `drafts` con `embedding IS NOT NULL`,
  `publicado_at > NOW() - INTERVAL '180 days'`, mismo `medio_id`.
- Cosine similitud > 0.7.
- Top 3 (descartar el draft actual si aparece).
- Anchor: n-grama (2-5 palabras) más largo del título del candidato que
  aparezca en el cuerpo del draft actual. Si no hay match léxico, el
  candidato se descarta (mejor sin enlace que enlace forzado).

## Imagen destacada (Pexels)

Query: `tema_final` + top 2-3 entidades.
Orientation: landscape. Size: large. Sin generación IA (política §6.1).
Si Pexels no devuelve nada, el draft entra sin imagen destacada
(`imagen_destacada_url=None`) y se loguea warning — NO se aborta el pipeline.

## JSON-LD

Schema.org `NewsArticle`. Campos: `headline`, `description`, `datePublished`,
`dateModified`, `author` (`Person` con `nombre_publico` del redactor),
`publisher` (`Organization` con el medio), `image` (array con URL Pexels si
existe), `mainEntityOfPage` (URL del CMS o placeholder), `about` (array de
entidades catalogadas con `@type` por tipo).

## OpenGraph + Twitter cards

`og:type=article`, `og:title=meta_title`, `og:description=meta_descr`,
`og:image=imagen_destacada_url`. Twitter card type=`summary_large_image`.

## Tags CMS

Lista de nombres canónicos de entidades (los adapters del CMS las mapean a
sus propios IDs/slugs en Fase 5).
