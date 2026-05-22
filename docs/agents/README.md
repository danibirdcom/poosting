# Agentes del pipeline

Cada nodo del pipeline tiene su spec aquí. Antes de tocar un nodo, lee el
markdown correspondiente.

- `detect.md` — consolida QUÉ se va a escribir (señal o tema manual).
- `research.md` — recopila fuentes verificables y extrae hechos.
- `write.md` — redacta el artículo según estilo del redactor.
- `review.md` — valida hechos, formato y registro.
- `enrich.md` — capa SEO/Discover: tags, links, JSON-LD, imagen.
- `publish.md` — publica al CMS o deja en bandeja.

## Contrato común

Cada nodo es una función pura `(state: PipelineState, deps: Deps) -> PipelineState`.

- Debe ser idempotente: re-ejecutarlo con mismo input produce mismo output.
- Persiste su input/output en `run_steps` con su nombre canónico.
- Errores recuperables: lanza excepción tipada; el orquestador hace retry con backoff.
- Errores no recuperables: marca el run como `fallido` con `error` legible en español.

Spec detallada de cada agente: pendiente para Fase 3 (pipeline básico).
