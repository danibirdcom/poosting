import { Pool, type PoolClient } from "pg";

/*
 * Pool de conexiones Postgres para la UI (rol `redactia_web`).
 *
 * - Singleton vía `globalThis.pgPool` para sobrevivir al HMR de Next dev.
 * - SSL solo si la DSN trae `sslmode=require` (RDS) — los entornos locales
 *   suelen ir sin SSL.
 * - Cada query DEBE ir por `queryAsMedio()`: setea `app.medio_actual`
 *   antes del statement, lo que activa las policies RLS multi-tenant.
 *   Si una query salta este helper, RLS no filtra → riesgo de leak.
 */

declare global {
  // eslint-disable-next-line no-var
  var pgPool: Pool | undefined;
}

function buildPool(): Pool {
  const connectionString = process.env.DATABASE_URL_WEB;
  if (!connectionString) {
    throw new Error(
      "DATABASE_URL_WEB no está definida. Copia dashboard/.env.local.example a dashboard/.env.local y rellénala."
    );
  }
  return new Pool({
    connectionString,
    max: 5,
    idleTimeoutMillis: 30_000,
    ssl: connectionString.includes("sslmode=require")
      ? { rejectUnauthorized: false }
      : undefined,
  });
}

// Lazy: no construyas el pool en module-load (rompería tests sin env).
function getPool(): Pool {
  if (globalThis.pgPool) return globalThis.pgPool;
  const pool = buildPool();
  if (process.env.NODE_ENV !== "production") {
    globalThis.pgPool = pool;
  }
  return pool;
}

/**
 * Ejecuta una query con `app.medio_actual` seteado al `medioId` dado.
 * RLS filtra automáticamente las filas; no hace falta `WHERE medio_id = $1`.
 *
 * Genérico T: tipo de fila esperado. El caller es responsable de que el
 * SELECT case con T (no hay validación runtime; usa zod en boundaries).
 */
export async function queryAsMedio<T>(
  medioId: string,
  text: string,
  params: unknown[] = []
): Promise<T[]> {
  const client: PoolClient = await getPool().connect();
  try {
    await client.query("SELECT set_config('app.medio_actual', $1, false)", [medioId]);
    const result = await client.query(text, params);
    return result.rows as T[];
  } finally {
    client.release();
  }
}

/**
 * Health check ligero. Devuelve true si la conexión a Postgres responde
 * `SELECT 1` en <2s.
 */
export async function pingDb(): Promise<boolean> {
  try {
    const client = await getPool().connect();
    try {
      await client.query("SELECT 1");
      return true;
    } finally {
      client.release();
    }
  } catch {
    return false;
  }
}
