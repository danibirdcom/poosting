# Política de imagen

Versión normativa: **CLAUDE.md §6.1 manda**. Este documento añade detalle
operativo y ejemplos. Cualquier conflicto se resuelve a favor de CLAUDE.md.

## Principios

1. **Nunca pasar por foto periodística lo que no lo es.** Ninguna imagen
   generada por IA puede confundirse con fotografía documental real.
2. **Personas reales identificables = banco con licencia, siempre.** Sin
   excepciones, ni siquiera "el redactor lo aprueba".
3. **Transparencia visible al lector.** Pie de foto y alt text con
   declaración explícita de IA cuando aplique.
4. **Metadatos C2PA y SynthID obligatorios** en cualquier imagen generada.

## Decisión rápida (árbol)

```
¿Imagen muestra una persona real identificable o un evento noticioso concreto?
├── Sí → banco con licencia (Pexels / Unsplash / Pixabay / EFE).
│        Si no se encuentra → marcar draft `requiere_imagen_humana`.
└── No
    ├── ¿Es infografía, gráfico o imagen con texto integrado?
    │   └── Sí → GPT Image 2
    └── ¿Es conceptual, ilustrativa, abstracta?
        └── Sí → Nano Banana 2 (estilo ilustración, NO fotorrealismo)
```

## Ejemplos

### Permitido
- Manos sobre un teclado para artículo sobre teletrabajo.
- Ilustración editorial con estilo declarado para opinión.
- Gráfico de barras con datos del INE generado por GPT Image 2.
- Imagen de un balón en un campo vacío para nota de previa deportiva.

### Prohibido
- "Foto" generada de Jorge Azcón firmando un decreto.
- Recreación fotorrealista de un incendio que ocurrió ayer en Huesca.
- Cualquier fotorrealismo de personajes públicos en situaciones inventadas.
- Imagen de un local concreto identificable que no se ha visitado.

## Metadatos obligatorios

| Campo | Valor |
|---|---|
| `alt_text` | "Imagen ilustrativa generada con IA: <descripción breve>" |
| `pie_foto` | "Imagen ilustrativa (IA). <opcional: contexto>" |
| `declaracion_ia_visible` | `true` |
| `synthid_present` | `true` (verificado tras generación) |
| `c2pa_metadata` | objeto C2PA con autor=medio + tool=Nano Banana 2 / GPT Image 2 |

## Router de imagen

`workers/src/image/router.py` decide ruta. Antes de generar:
1. Clasifica el sujeto del artículo (NER + heurística).
2. Si hay persona real → intenta bancos en orden:
   `[EFE si licenciado, Europa Press si licenciado, Pexels, Unsplash, Pixabay]`.
3. Si nada matchea con relevancia suficiente → flag `requiere_imagen_humana`.
4. Si tema abstracto → Nano Banana 2 con prompt en `prompts/image_*.md`.
5. Si infografía → GPT Image 2.

Toda decisión queda registrada en `imagenes_articulo` para auditoría.
