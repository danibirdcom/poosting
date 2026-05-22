# Runbook: Budget enforcement de APIs externas

## Resumen

El gasto en APIs externas (X API en Fase 2, posiblemente Voyage en Fase 3+)
está limitado por (medio, servicio, mes) mediante la tabla `presupuestos_api`
y la función `reservar()` en `workers/src/trends/budget.py`.

## Cómo funciona

### Reserva atómica antes de cada llamada

Antes de gastar un céntimo, el código pide a la BD que reserve el coste
estimado contra el budget. La reserva es una sola query atómica:

```sql
UPDATE presupuestos_api
   SET gasto_mes_actual_eur = gasto_mes_actual_eur + $coste,
       actualizado_at = NOW()
 WHERE medio_id = $medio
   AND servicio = $servicio
   AND mes_ref  = $mes
   AND (gasto_mes_actual_eur + $coste) <= (budget_mensual_eur * 0.95)
RETURNING id, gasto_mes_actual_eur;
```

Si la fila no se devuelve (`RETURNING` vacío), una de dos:
- No hay budget configurado para ese (medio, servicio, mes_ref).
- La reserva superaría el 95% del budget.

En ambos casos lanzamos `BudgetExceededError` y NO se hace la llamada externa.

### Liberación en caso de error tras reservar

Si la llamada HTTP falla **después** de reservar (rate limit 429, 5xx, timeout,
excepción), `liberar()` devuelve el importe reservado:

```sql
UPDATE presupuestos_api
   SET gasto_mes_actual_eur = GREATEST(0, gasto_mes_actual_eur - $importe)
 WHERE id = $presupuesto_id;
```

El `GREATEST(0, ...)` + el `CHECK (gasto_mes_actual_eur >= 0)` de la tabla
garantizan que nunca dejamos saldo negativo aunque haya bugs en el caller.

## Dónde vive el hard_stop

**No es una columna configurable por-medio.** Es una constante en código:

- Archivo: `workers/src/trends/budget.py`
- Línea: `UMBRAL_FRACCION = Decimal("0.95")`

Si la fracción gastada superaría 0.95 × budget, se aborta. Es **deliberado**
no tenerlo en BD en Fase 2:

1. Los 3 medios iniciales usan el mismo umbral.
2. Cambiarlo sin redeploy no es un caso real (es una constante de seguridad,
   no un dial editorial).
3. Si en Fase 5+ aparece un medio con tolerancia distinta, añadimos columna
   `hard_stop_fraccion NUMERIC` a `presupuestos_api` y cambiamos `reservar`
   para leerla con fallback a 0.95. Migración trivial.

## Dónde se invoca

| Llamada | Archivo:línea | Coste estimado |
|---|---|---|
| `XApiDetector.detectar` | `workers/src/trends/x_api.py` (antes del HTTP GET) | `X_READ_COST_EUR = 0.0046` |
| (futuro) `VoyageEmbeddings.embed` masivo | pendiente | TBD por documento |

## Cómo dar de alta un budget para un nuevo medio

```sql
INSERT INTO presupuestos_api (
  medio_id, servicio, budget_mensual_eur, mes_ref
)
VALUES (
  '<uuid_medio>', 'x_api', 25.00, date_trunc('month', NOW())::date
);
```

O usar el seed `scripts/seed_hoy_aragon.py` como plantilla (ya inserta el
budget de Hoy Aragón con 25 €/mes para X API).

## Renovación mensual

Cada `mes_ref` es una fila nueva. **Hay que crear la fila del mes nuevo
manualmente** (no se renueva automáticamente). Cuando llega el 1 de mes
y no existe fila para `mes_ref = <primer día>`, `reservar` lanzará
`BudgetExceededError` con razón `budget_no_configurado` y el detector
hará skip silencioso.

Pendiente para Fase 7 (notificaciones): cron del día 28 que crea la fila
del mes siguiente automáticamente y avisa por email si el mes en curso
ha superado el 80% del budget.

## Monitorización

Query útil para ver el estado de los budgets:

```sql
SELECT m.slug, p.servicio, p.budget_mensual_eur, p.gasto_mes_actual_eur,
       ROUND(p.gasto_mes_actual_eur / p.budget_mensual_eur * 100, 1) AS pct,
       p.mes_ref
  FROM presupuestos_api p
  JOIN medios m ON m.id = p.medio_id
 WHERE p.mes_ref = date_trunc('month', NOW())::date
 ORDER BY pct DESC;
```

Alertar manualmente si `pct > 80` mientras no tengamos notificaciones.

## Tests

`workers/tests/trends/test_budget.py` cubre los 4 casos críticos:
- Reserva dentro del budget actualiza el gasto.
- Reserva que superaría el 95% lanza `BudgetExceededError`.
- Reserva sin budget configurado lanza `BudgetExceededError`.
- `liberar` devuelve el importe correctamente.

Más `test_x_api.py::test_x_api_budget_excedido_bloquea` verifica que el
detector NI SIQUIERA hace la llamada HTTP si la reserva falla.
