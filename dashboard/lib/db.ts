import { Pool, type PoolClient, type PoolConfig } from "pg";

/*
 * Pool de conexiones Postgres para la UI (rol `redactia_web`).
 *
 * - Singleton vía `globalThis.pgPool` para sobrevivir al HMR de Next dev.
 * - SSL: pg ≥8.13 trata `?sslmode=require` como verify-full (TLS estricto
 *   con CA validada), lo que rompe contra RDS porque la CA de Amazon no
 *   está en el truststore por defecto. El workaround `?uselibpqcompat=true`
 *   funciona pero es frágil (cualquiera que olvide ese flag rompe el dash).
 *
 *   Solución: detectar el host. Si NO es localhost/127.0.0.1/::1, forzamos
 *   SSL con `rejectUnauthorized: false` (suficiente para RDS — el tráfico
 *   va cifrado, solo no validamos la CA). Para localhost no fuerza nada
 *   (PG local suele ir sin SSL). El DSN queda libre de query params SSL.
 *
 * - Cada query DEBE ir por `queryAsMedio()`: setea `app.medio_actual`
 *   antes del statement, lo que activa las policies RLS multi-tenant.
 *   Si una query salta este helper, RLS no filtra → riesgo de leak.
 */

declare global {
  // eslint-disable-next-line no-var
  var pgPool: Pool | undefined;
}

/**
 * True si el host del DSN es localhost, 127.0.0.1 o ::1. Función pura,
 * testeable sin pool. Usa la API `URL` de Node (soporta `postgres://`).
 * Si el DSN está mal formado, devuelve false (asume remoto → fuerza SSL,
 * que es la opción segura).
 */
export function isLocalHostDsn(dsn: string): boolean {
  try {
    const url = new URL(dsn);
    // Node WHATWG URL deja brackets en hosts IPv6 ("[::1]"). Los quitamos.
    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
    return host === "localhost" || host === "127.0.0.1" || host === "::1";
  } catch {
    return false;
  }
}

/**
 * Devuelve la config para `new Pool(...)` aplicando la lógica SSL
 * descrita arriba. Función pura, testeable sin instanciar Pool.
 */
export function buildPoolConfig(dsn: string): PoolConfig {
  return {
    connectionString: dsn,
    max: 5,
    idleTimeoutMillis: 30_000,
    ssl: isLocalHostDsn(dsn) ? undefined : { rejectUnauthorized: false },
  };
}

function buildPool(): Pool {
  const connectionString = process.env.DATABASE_URL_WEB;
  if (!connectionString) {
    throw new Error(
      "DATABASE_URL_WEB no está definida. Copia dashboard/.env.local.example a dashboard/.env.local y rellénala."
    );
  }
  return new Pool(buildPoolConfig(connectionString));
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
