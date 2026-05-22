# Runbook: CI con RDS compartido

## Resumen

El CI corre tests reales contra una BD Postgres en RDS (eu-west-1). El SG
del RDS solo deja entrar IPs explícitamente autorizadas. El runner de
GitHub Actions:

1. Obtiene su IP pública.
2. Se autoriza a sí mismo en el SG (`aws ec2 authorize-security-group-ingress`).
3. Resetea la BD de CI (drop schema + recrea extensiones).
4. Aplica todas las migraciones como `redactia_admin` (owner).
5. Concede pertenencia del rol grupo `redactia_app` al usuario `redactia_app_ci`.
6. Aplica los seeds.
7. Corre los tests como `redactia_app_ci` (no-owner; sometido a RLS).
8. **Siempre** revoca la regla del SG (`if: always()`).

## Diagrama del flujo

```
Push/PR ──► Runner GH Actions ──► [open SG] ──► reset+migrate+seed ──► pytest
                                                                          │
                                       ┌──────────────────────────────────┘
                                       ▼
                                  [revoke SG]  ◄── if: always()
```

## Secrets necesarios en el repo

| Secret | Contenido | Notas |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | IAM con permisos limitados | Solo `ec2:Authorize/Revoke/DescribeSecurityGroups` |
| `AWS_SECRET_ACCESS_KEY` | — | — |
| `AWS_REGION` | `eu-west-1` | — |
| `RDS_SG_ID` | `sg-xxxxxxxx` | SG del RDS |
| `DATABASE_URL_CI` | DSN del usuario app | `redactia_app_ci`, NO owner |
| `DATABASE_URL_ADMIN_CI` | DSN del usuario admin | `redactia_admin`, owner |

## Roles de Postgres

| Rol | Propósito | Privilegios |
|---|---|---|
| `redactia_admin` | Aplica migraciones y seeds. Owner de las tablas. | Todo. |
| `redactia_app` | Rol grupo. No hace login. Contrato de privilegios para apps. | CRUD según `002_grants.sql`. |
| `redactia_app_ci` | Usuario de CI. Hereda de `redactia_app`. | Lo que herede + sujeto a RLS. |
| `redactia_app_dev` | (futuro) Usuario de desarrollo. | Idem. |
| `redactia_app_prod` | (futuro) Usuario de producción. | Idem. |

**RLS con FORCE**: incluso `redactia_admin` (owner) está sujeto a las policies.
Para operaciones de admin que necesiten ver across-tenant, usar funciones
`SECURITY DEFINER` explícitas — nunca abrir agujeros en las policies.

## Verificar que el SG no tiene reglas residuales

```bash
aws ec2 describe-security-groups \
  --group-ids sg-XXXXXXXX \
  --region eu-west-1 \
  --query 'SecurityGroups[0].IpPermissions[?ToPort==`5432`]' \
  --output table
```

En estado limpio solo debe verse la regla permanente (si la hay) que
permite acceso desde tu IP de trabajo. Cualquier descripción que empiece
por `ci-<run_id>` y que esté hace > 30 min indica un cleanup fallido.

### Limpieza manual si quedaron reglas residuales

```bash
aws ec2 describe-security-groups \
  --group-ids sg-XXXXXXXX \
  --query 'SecurityGroups[0].IpPermissions' \
  --output json > /tmp/sg.json

# Inspecciona /tmp/sg.json, identifica las reglas con Description "ci-<run_id>"
# y revócalas:

aws ec2 revoke-security-group-ingress \
  --group-id sg-XXXXXXXX \
  --ip-permissions 'IpProtocol=tcp,FromPort=5432,ToPort=5432,IpRanges=[{CidrIp=W.X.Y.Z/32}]'
```

## Troubleshooting

### El job falla en "Detectar IP del runner"
Probablemente `checkip.amazonaws.com` está dando timeout. Reintentar el job;
si persiste, sustituir por `ifconfig.me` o `api.ipify.org`.

### El job falla en psql con "connection timed out"
La regla SG no se aplicó o no apunta a la IP correcta. Verifica el step
"Detectar IP" y el output del `authorize-security-group-ingress`. Reintentar.

### El test de RLS falla con "permission denied for table redactores"
El `GRANT redactia_app TO redactia_app_ci` no se ejecutó o se hizo
después de la conexión. La conexión actual no recoge nuevos grants
automáticamente — reconectar (cosa que ya hace el siguiente run).

### El test "rls_insert_rechaza_medio_ajeno" no lanza el error esperado
Causa: la migración 001 no tiene `WITH CHECK` en las policies. Verificar
que ese bloque sigue presente en `db/migrations/001_initial.sql` §RLS.

### El SG llegó a 60 reglas (límite)
Ha habido cleanups fallidos acumulados. Limpiar manualmente (ver arriba)
y revisar logs de Actions de las últimas 2 semanas para encontrar el job
que fallaba a la mitad sin pasar por el cleanup.

## Cómo escalar el coste

El RDS de CI no necesita estar siempre encendido. Opciones:
- **Aurora Serverless v2**: escala a 0.5 ACU en idle (~5 €/mes). Buena para
  CI esporádico.
- **db.t4g.micro**: barato pero siempre encendido (~13 €/mes).
- **Stop/Start con EventBridge**: parar el RDS fuera de horas. Limitación
  RDS: máx 7 días detenido, luego se autoarranca.

## Lecciones aprendidas — Fase 1

### Typo en el secret `DATABASE_URL_CI`
El secret se copió con un error en el hostname, distinto al de
`DATABASE_URL_ADMIN_CI`. Los pasos previos (psql como admin) pasaban; los
tests con asyncpg fallaban con `socket.gaierror: [Errno -2] Name or service
not known`. Coste: 2 runs en rojo + el tiempo de diagnosticar a ciegas.

**Mitigación adoptada:** step "Diagnóstico de conectividad" que:
1. Parsea ambos DSNs e imprime `scheme/host/port/user/db` (sin password).
2. Hace un `psql "$APP_URL" -c 'SELECT current_user, current_database();'`
   antes de pytest, así un secret roto falla con mensaje claro en lugar
   de gaierror enterrado en stack trace de asyncpg.

**Mejora pendiente:** validar el formato del DSN en el propio step y abortar
si `hostname is None` o `scheme not in {postgres, postgresql}` antes de
intentar conectar. Esto sería instantáneo y aún más claro. Cuando lo
implementemos:

```python
# python en el step, antes del psql:
u = urlparse(os.environ["APP_URL"])
assert u.hostname, "APP_URL sin hostname — revisa el secret"
assert u.scheme in ("postgres", "postgresql"), f"scheme inesperado: {u.scheme}"
assert u.port, "APP_URL sin puerto"
```

### `astral-sh/setup-uv@v3` obsoleto
La action moderna espera al menos `@v5`. Con `@v3` el job moría en ~7 s
en el setup de uv sin mensaje útil (artefactos caducados en el release).
Lección: pinear versiones específicas (`@v5.x`) sí, pero **no** quedarse en
versiones major antiguas de actions populares — revisar al inicio de cada
fase nueva. Para `setup-uv` el changelog está en
`github.com/astral-sh/setup-uv/releases`.

### Lint en CI fue el primer cuello de botella tras los DNS
`ruff check src tests` falló por UP045 (`Optional[X]` → `X | None`) y
SIM117 (`async with a: async with b:` → `async with a, b:`) en
`api/src/db/pool.py`. Lección: correr `make lint` en local antes de
push de cambios grandes. El pre-commit hook con ruff lo evitará — sumar
en la próxima fase.
