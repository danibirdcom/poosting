# Formato de la guía de estilo por redactor

Cada `estilos_redactor.guia_estilo_md` es un markdown estructurado que se
inyecta tal cual al prompt del nodo `write`. Debe seguir el siguiente
formato canónico para que el LLM lo procese bien y para que las métricas
objetivas puedan extraerse de forma fiable.

## Estructura

```markdown
# Guía de estilo — <Nombre del redactor>
Medio: <slug>
Versión: <N>
Generada: <YYYY-MM-DD>

## 1. Voz e identidad
- Tono: <p.ej. "cercano pero riguroso, sin coloquialismos">
- Persona narrativa: <1ª persona del plural / 3ª persona impersonal>
- Registro: <formal / semiformal / coloquial>
- Postura editorial: <p.ej. "no opina, expone hechos">

## 2. Estructura del artículo
- Apertura preferida: <"contexto antes del dato" | "dato antes del contexto">
- Longitud media: <X palabras>
- H2 cada: <X párrafos en media>
- Cierre típico: <"resumen + próximo paso" | "frase impactante" | "datos">

## 3. Sintaxis
- Longitud media de frase: <X palabras> (rango <a>–<b>)
- Longitud media de párrafo: <X frases>
- Voz pasiva: <% del total>
- Subordinación: <baja/media/alta>

## 4. Vocabulario
- Palabras evitadas: [lista]
- Palabras preferidas para conceptos comunes: [mapeo]
- Anglicismos: <admitidos / evitar / contextual>
- Tecnicismos: <con glosa entre paréntesis / sin glosa>

## 5. Convenciones de formato
- Comillas: <tipográficas «» / inglesas "">
- Cifras: <"hasta nueve en letra" / "siempre en cifra">
- Cargos: <minúscula / mayúscula>
- Topónimos: <forma oficial / forma popular>

## 6. Manejo de fuentes y citas
- Citas textuales: <"al final del párrafo de contexto" | "abriendo párrafo">
- Atribución: <"según fuentes" / "fuentes consultadas afirman">
- Cita máxima: <X palabras>

## 7. Lo que NO hace este redactor
- <p.ej. "nunca usa exclamaciones">
- <p.ej. "nunca abre con pregunta retórica">
- <p.ej. "nunca menciona redes sociales en titular">
```

## Cómo se genera

`workers/src/style_profile/builder.py` recibe N ejemplos del redactor
(`ejemplos_redactor`) y produce esta guía siguiendo el formato canónico.
El prompt vive en `workers/src/pipeline/prompts/style_builder.md` y está
versionado.

## Cómo se actualiza

Cuando un redactor (o editor jefe) corrige > 20 drafts del redactor virtual
desde la última versión, `updater.py` agrupa las correcciones por categoría
(`tono`, `estructura`, `vocab`, `factual`) y propone una nueva versión.
El editor jefe debe aprobarla antes de marcarla `activo = TRUE`.

## Métricas objetivas

Las secciones 3 (sintaxis) deben tener métricas calculadas, no inferidas.
`metrics.py` extrae:
- longitud media de frase y párrafo
- ratio de voz pasiva
- distribución de longitudes (mediana, p10, p90)
- léxico distintivo vs corpus general (TF-IDF)

Se almacenan en `estilos_redactor.metricas` como JSON.
