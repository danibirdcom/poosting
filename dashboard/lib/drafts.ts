import { queryAsMedio } from "@/lib/db";
import {
  ESTADOS_DRAFT,
  PAGE_SIZE,
  type DraftFilters,
  type DraftRow,
  type EstadoDraft,
  type OrdenDraft,
} from "@/lib/drafts-types";

// Re-exporta los tipos/constantes para que el resto del código pueda
// importar todo desde `@/lib/drafts`. Los Client Components que solo
// necesitan enums deben importar de `@/lib/drafts-types` directamente
// (sin arrastrar `pg` al bundle del navegador).
export {
  ESTADOS_DRAFT,
  ORDENES_DRAFT,
  PAGE_SIZE,
  type DraftFilters,
  type DraftRow,
  type EstadoDraft,
  type OrdenDraft,
} from "@/lib/drafts-types";

/*
 * Acceso de lectura a la tabla `drafts` para la bandeja editorial.
 *
 * Se evita asumir columnas que NO existen en el schema (verificado contra
 * `db/migrations/001_initial.sql`):
 *   - `drafts.redactor_id` no existe → JOIN: drafts → runs.redactor_id → redactores.
 *   - `drafts.review_errores` no existe → derivado de `run_steps.output->'errores'`.
 *   - `drafts.requiere_revision_humana` no existe → derivado de
 *     `run_steps.output->>'requiere_revision_humana'`.
 *
 * Todos los JOINs son LEFT JOIN porque:
 *   - un draft puede no tener `run` válido (orphan).
 *   - un run puede no tener `redactor_id` (caso manual sin asignar).
 *   - un run puede haber abortado en `research` → no hay fila para
 *     step='review' → `rs.output` es NULL → COALESCE devuelve 0/false.
 *
 * Multi-tenancy: el filtro `medio_id = ...` lo hace RLS via
 * `app.medio_actual` (set por `queryAsMedio`). Nunca añadir WHERE manual.
 */

type DbRow = {
  id: string;
  titulo: string;
  estado: EstadoDraft;
  creado_at: Date | string;
  redactor_nombre: string | null;
  requiere_revision: boolean;
  // jsonb_array_length devuelve int (number); en algunos drivers viene como string.
  n_errores: number | string;
};

function orderClause(orden: OrdenDraft | undefined): string {
  switch (orden) {
    case "antiguo":
      return "d.creado_at ASC";
    case "titulo":
      return "d.titulo ASC";
    case "reciente":
    default:
      return "d.creado_at DESC";
  }
}

type FiltrosNormalizados = {
  estados: EstadoDraft[] | null;
  q: string | null;
  orden: OrdenDraft;
  page: number;
};

function normalizar(filtros: DraftFilters): FiltrosNormalizados {
  const estados =
    filtros.estados && filtros.estados.length > 0
      ? filtros.estados.filter((e): e is EstadoDraft =>
          (ESTADOS_DRAFT as readonly string[]).includes(e)
        )
      : null;
  const q = filtros.q?.trim();
  const orden: OrdenDraft = filtros.orden ?? "reciente";
  const page = Math.max(1, Math.floor(filtros.page ?? 1));
  return {
    estados: estados && estados.length > 0 ? estados : null,
    q: q && q.length > 0 ? q : null,
    orden,
    page,
  };
}

/** Lista paginada de drafts del medio, con datos derivados de run_steps. */
export async function listDrafts(
  medioId: string,
  filtros: DraftFilters = {}
): Promise<DraftRow[]> {
  const { estados, q, orden, page } = normalizar(filtros);
  const offset = (page - 1) * PAGE_SIZE;
  const sql = `
    SELECT
      d.id::text                                                        AS id,
      d.titulo                                                          AS titulo,
      d.estado                                                          AS estado,
      d.creado_at                                                       AS creado_at,
      r.nombre_publico                                                  AS redactor_nombre,
      COALESCE((rs.output->>'requiere_revision_humana')::bool, FALSE)   AS requiere_revision,
      COALESCE(jsonb_array_length(rs.output->'errores'), 0)::int         AS n_errores
    FROM drafts d
    LEFT JOIN runs ru        ON ru.id = d.run_id
    LEFT JOIN redactores r   ON r.id = ru.redactor_id
    LEFT JOIN run_steps rs   ON rs.run_id = d.run_id
                            AND rs.step_nombre = 'review'
                            AND rs.estado = 'completado'
    WHERE
      ($1::text[] IS NULL OR d.estado = ANY($1))
      AND ($2::text IS NULL OR d.titulo ILIKE '%' || $2 || '%')
    ORDER BY ${orderClause(orden)}
    LIMIT $3 OFFSET $4
  `;
  const rows = await queryAsMedio<DbRow>(medioId, sql, [estados, q, PAGE_SIZE, offset]);
  return rows.map((r) => ({
    id: r.id,
    titulo: r.titulo,
    estado: r.estado,
    creadoAt: r.creado_at instanceof Date ? r.creado_at : new Date(r.creado_at),
    redactorNombre: r.redactor_nombre,
    requiereRevision: r.requiere_revision,
    nErrores: typeof r.n_errores === "string" ? parseInt(r.n_errores, 10) : r.n_errores,
  }));
}

/** Conteo total con los mismos filtros (para paginación). */
export async function countDrafts(
  medioId: string,
  filtros: DraftFilters = {}
): Promise<number> {
  const { estados, q } = normalizar(filtros);
  const sql = `
    SELECT COUNT(*)::int AS n
    FROM drafts d
    WHERE
      ($1::text[] IS NULL OR d.estado = ANY($1))
      AND ($2::text IS NULL OR d.titulo ILIKE '%' || $2 || '%')
  `;
  const rows = await queryAsMedio<{ n: number }>(medioId, sql, [estados, q]);
  return rows[0]?.n ?? 0;
}
