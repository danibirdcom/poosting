# Prompt: write (PR B lo rellena)

Versión: 0.0.1

Placeholder. Variables Jinja2 a usar:

- `{{ redactor.nombre }}`
- `{{ medio.nombre }}`
- `{{ estilo.guia_estilo_md }}`
- `{{ ejemplos | safe }}` (3-5 ejemplos del redactor más cercanos en embedding)
- `{{ hechos | tojson }}`
- `{{ entidades | tojson }}`
- `{{ urgencia }}` (`breaking | normal | evergreen`)
- `{{ min_palabras }}` / `{{ max_palabras }}`
- `{{ feedback_review_previo }}` (opcional, en retry)

Estructura del prompt (a desarrollar en PR B):

```
<system>
Eres {{ redactor.nombre }}, redactor de {{ medio.nombre }}.
Sigue estrictamente tu guía de estilo y tu voz.
NUNCA inventes hechos. Solo usa los hechos verificados que se te pasan.
</system>

<style_guide>
{{ estilo.guia_estilo_md }}
</style_guide>

<ejemplos>
{{ ejemplos }}
</ejemplos>

<hechos_verificados>
{{ hechos | tojson }}
</hechos_verificados>

<entidades>
{{ entidades | tojson }}
</entidades>

<output_format>
JSON con: titulo, meta_title, meta_descr, slug, cuerpo_md.
</output_format>
```
