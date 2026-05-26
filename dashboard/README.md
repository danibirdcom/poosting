# Redactia Dashboard

UI Next.js 15 (App Router, React 19) para Redactia. Bandeja editorial,
editor de drafts, trazabilidad y configuración multi-tenant.

Stack: Next 15 · React 19 · TypeScript strict · Tailwind · shadcn/ui
(new-york / zinc) · pg (node-postgres) · date-fns · vitest.

## Setup local

1. **Aplicar migraciones 006 + 007** a la BD (desde la raíz del repo):
   ```bash
   # Como superuser de Postgres (las migraciones crean rol y permisos):
   psql "$DATABASE_URL_ADMIN" -f db/migrations/006_auditoria_humano.sql
   psql "$DATABASE_URL_ADMIN" -f db/migrations/007_redactia_web_role.sql
   ```

2. **Crear usuario login con membership en `redactia_web`** (por entorno,
   no en la migración):
   ```sql
   CREATE ROLE redactia_web_dev LOGIN PASSWORD 'tu-password-fuerte';
   GRANT redactia_web TO redactia_web_dev;
   ```

3. **Configurar `.env.local`**:
   ```bash
   cp dashboard/.env.local.example dashboard/.env.local
   # Edita DATABASE_URL_WEB con el password elegido y MEDIO_ID_HARDCODED
   ```

4. **Instalar y arrancar**:
   ```bash
   cd dashboard
   npm install
   npm run dev
   # → http://localhost:3000 (redirige a /bandeja)
   ```

## Scripts

| script           | qué hace                                    |
|------------------|---------------------------------------------|
| `npm run dev`    | next dev (hot reload)                       |
| `npm run build`  | next build (producción)                     |
| `npm run start`  | next start (servir build)                   |
| `npm run lint`   | next lint                                   |
| `npm run typecheck` | tsc --noEmit                             |
| `npm test`       | vitest run                                  |

## Estructura

```
dashboard/
├── app/                  # Rutas (App Router)
│   ├── layout.tsx        # Layout root (sidebar + header)
│   ├── page.tsx          # Redirect → /bandeja
│   ├── bandeja/          # Pantalla principal
│   ├── api/health/       # GET /api/health
│   └── globals.css
├── components/
│   ├── layout/           # Sidebar, Header
│   └── ui/               # shadcn (button, badge, skeleton, …)
├── lib/
│   ├── db.ts             # Pool pg + queryAsMedio (RLS)
│   ├── format.ts         # Fechas, truncado
│   └── utils.ts          # cn() shadcn
├── __tests__/            # vitest
└── package.json
```

## Multi-tenancy

Toda query a la BD pasa por `queryAsMedio(medioId, sql, params)` en
`lib/db.ts`. El helper setea `app.medio_actual` antes del statement, lo
que activa las policies RLS de Postgres. **Nunca uses `pool.query()`
directo** — RLS no filtraría y habría leak entre tenants.

En PR1 `medioId` viene de `process.env.MEDIO_ID_HARDCODED`. En PR2 viene
de la sesión de NextAuth (rol del usuario + tenant activo).

## Plan de Fase 4

- **PR1 (este):** scaffolding + bandeja read-only.
- **PR2:** NextAuth + editor de draft + aprobar/rechazar/archivar +
  auditoria_humano funcional.
- **PR3:** deploy AWS Amplify + redactia.birdcom.es.
- **PR4:** trazabilidad (`run_steps`) + lanzar run manual desde UI.

Ver `CLAUDE.md` §10.
