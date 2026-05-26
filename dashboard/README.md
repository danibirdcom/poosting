# Redactia Dashboard

UI Next.js 15 (App Router, React 19) para Redactia. Bandeja editorial,
editor de drafts, trazabilidad y configuración multi-tenant.

Stack: Next 15 · React 19 · TypeScript strict · Tailwind · shadcn/ui
(new-york / zinc) · pg (node-postgres) · NextAuth v5 · argon2id · zod ·
date-fns · vitest.

## Setup local

1. **Aplicar migraciones 006 + 007 + 008** a la BD (desde la raíz del repo):
   ```bash
   # Como superuser de Postgres:
   psql "$DATABASE_URL_ADMIN" -f db/migrations/006_auditoria_humano.sql
   psql "$DATABASE_URL_ADMIN" -f db/migrations/007_redactia_web_role.sql
   psql "$DATABASE_URL_ADMIN" -f db/migrations/008_auth_grants.sql
   ```

2. **Crear usuario login con membership en `redactia_web`** (por entorno):
   ```sql
   CREATE ROLE redactia_web_dev LOGIN PASSWORD 'tu-password-fuerte';
   GRANT redactia_web TO redactia_web_dev;
   ```

3. **Configurar `.env.local`**:
   ```bash
   cp dashboard/.env.local.example dashboard/.env.local
   # Edita DATABASE_URL_WEB con el password elegido y genera un
   # AUTH_SECRET con `openssl rand -base64 32`.
   ```

4. **Crear el primer usuario** (paso a paso):
   ```bash
   cd dashboard
   npm install
   # Hashea la contraseña:
   echo "tu-password-segura" | npm run -s hash-password
   # → copia el hash $argon2id$...
   ```

   Y ejecuta este SQL contra la BD (como `redactia_admin` o equivalente):
   ```sql
   -- 1. Asegúrate de tener un medio (Hoy Aragón en este ejemplo):
   INSERT INTO medios (slug, nombre, cms_tipo)
   VALUES ('hoy-aragon', 'Hoy Aragón', 'opendemas')
   ON CONFLICT (slug) DO NOTHING;

   -- 2. Crea el usuario con el hash que generaste:
   INSERT INTO usuarios (email, nombre, password_hash, rol_global)
   VALUES (
     'dani@birdcom.es',
     'Dani Moreno',
     '<HASH_ARGON2>',          -- pega el output de hash-password aquí
     'superadmin'
   )
   ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

   -- 3. Asocia el usuario al medio como editor_jefe:
   INSERT INTO usuarios_medios (usuario_id, medio_id, rol)
   SELECT u.id, m.id, 'editor_jefe'
   FROM usuarios u, medios m
   WHERE u.email = 'dani@birdcom.es' AND m.slug = 'hoy-aragon'
   ON CONFLICT DO NOTHING;
   ```

5. **Arrancar dev**:
   ```bash
   npm run dev
   # → http://localhost:3000 (redirige a /login)
   ```

## Scripts

| script                    | qué hace                                        |
|---------------------------|-------------------------------------------------|
| `npm run dev`             | next dev                                        |
| `npm run build`           | next build                                      |
| `npm run start`           | next start                                      |
| `npm run lint`            | next lint                                       |
| `npm run typecheck`       | tsc --noEmit                                    |
| `npm test`                | vitest run                                      |
| `npm run hash-password`   | argon2id por stdin para crear usuarios          |

## Estructura

```
dashboard/
├── app/
│   ├── (app)/                # rutas autenticadas (sidebar + header)
│   │   ├── layout.tsx
│   │   └── bandeja/
│   │       ├── page.tsx          # lista
│   │       └── [draftId]/        # editor + acciones
│   ├── (auth)/login/         # /login (sin chrome)
│   ├── api/auth/[...nextauth]/ # handler NextAuth v5
│   ├── api/health/
│   ├── layout.tsx            # root mínimo
│   └── page.tsx              # redirect → /login
├── auth.ts                   # NextAuth config (Node runtime)
├── auth.config.ts            # config edge-safe (middleware)
├── middleware.ts             # protección de rutas
├── components/
│   ├── auth/                 # login-form, logout-button
│   ├── editor/               # draft-editor, side-panel, footer-acciones, …
│   ├── bandeja/
│   ├── layout/
│   └── ui/                   # shadcn (button, input, label, dialog, …)
├── lib/
│   ├── auth-actions.ts       # signOut action
│   ├── auth-utils.ts         # getSessionWithMedio, requireMedioId
│   ├── auditoria.ts          # registerAuditEvent
│   ├── cms/publisher.ts      # CmsPublisher + NoOpPublisher
│   ├── db.ts                 # pool pg + queryAsMedio + queryAsUser
│   ├── draft-detail.ts       # getDraftBundle
│   ├── drafts.ts             # listDrafts, countDrafts
│   ├── drafts-update.ts      # save/approve/reject/archive
│   └── format.ts
├── scripts/hash-password.ts  # CLI argon2id
└── types/next-auth.d.ts      # augmentación Session/JWT
```

## Auth

- **NextAuth v5** con Credentials provider.
- Password storage: argon2id (memoryCost 19456, timeCost 2, parallelism 1 —
  preset OWASP 2024). Columna `usuarios.password_hash`.
- Session: JWT en cookie httpOnly, 12h TTL.
- El JWT lleva `medioId`, `medioRol`, `rolGlobal`. Multi-medio queda
  para PR futuro: por ahora se elige el primer `usuarios_medios` del
  usuario ordenado por uuid.
- `middleware.ts` (edge runtime) protege `/bandeja`, `/runs`, `/admin`.
- Sin registro público: usuarios se crean por SQL.

## CMS Publisher

`lib/cms/publisher.ts` define `CmsPublisher`. En PR2 solo existe
`NoOpPublisher` (devuelve error). La acción "Aprobar" únicamente
cambia `drafts.estado` a `'aprobado'` en BD; **no publica al CMS**.
La publicación real de Hoy Aragón (Opennemas) entra en PR3.

## Multi-tenancy

Toda query a la BD pasa por `queryAsMedio(medioId, sql, params)` o
`queryAsUser(sql, params)`. Ambos setean `app.medio_actual` antes del
statement → RLS de Postgres filtra. **Nunca uses `pool.query()` directo
salvo en `auth.ts`** (lookup de usuarios al login, tablas sin RLS).

## Plan de Fase 4

- **PR1:** scaffolding + bandeja read-only.
- **PR2 (este):** NextAuth + editor + aprobar/rechazar/archivar +
  `auditoria_humano` + `CmsPublisher` (NoOp).
- **PR3:** deploy AWS Amplify + dominio `redactia.birdcom.es` +
  `OpennemasPublisher`.
- **PR4:** trazabilidad (`run_steps`) + lanzar run manual desde UI.

Ver `CLAUDE.md` §16.
