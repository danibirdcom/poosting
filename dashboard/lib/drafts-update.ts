import { z } from "zod";
import { queryAsMedio } from "@/lib/db";
import {
  diffDraftSnapshots,
  registerAuditEvent,
  type AuditDiff,
} from "@/lib/auditoria";

/*
 * Mutaciones sobre `drafts` desde la UI: guardar edición, aprobar,
 * rechazar, archivar.
 *
 * Cada mutación:
 *   1. Aplica el UPDATE (RLS valida medio_id automáticamente).
 *   2. Inserta una fila en `auditoria_humano` con la acción.
 *
 * Sin transacción explícita: el riesgo de inconsistencia (UPDATE OK,
 * INSERT falla) es bajo (mismo schema, misma conexión lógica), y
 * `auditoria_humano` queda como log perdible — la fuente de verdad
 * editorial es `drafts.estado`. Si en el futuro hace falta atomicidad
 * estricta, encapsular ambas operaciones bajo un BEGIN/COMMIT vía
 * un client del pool.
 */

// Validación tolerante: meta_title hasta 75 (LLMs a veces se pasan), meta_descr
// hasta 200. El usuario corrige inline. Slug solo lowercase + dígitos + '-'.
export const SaveDraftSchema = z.object({
  titulo: z.string().trim().min(1, "Título obligatorio").max(200),
  meta_title: z.string().trim().min(20, "Mínimo 20 chars").max(75).nullable(),
  meta_descr: z
    .string()
    .trim()
    .min(80, "Mínimo 80 chars")
    .max(200, "Máximo 200 chars")
    .nullable(),
  slug: z
    .string()
    .trim()
    .min(1, "Slug obligatorio")
    .max(120)
    .regex(/^[a-z0-9-]+$/, "Solo a-z, 0-9 y '-'")
    .nullable(),
  cuerpo_md: z.string().min(50, "Cuerpo demasiado corto").max(50_000),
});

export type SaveDraftInput = z.infer<typeof SaveDraftSchema>;

export const RejectDraftSchema = z.object({
  motivo: z
    .string()
    .trim()
    .min(10, "Mínimo 10 caracteres explicando el motivo")
    .max(1000),
});

export type RejectDraftInput = z.infer<typeof RejectDraftSchema>;

type DraftSnapshot = {
  titulo: string;
  meta_title: string | null;
  meta_descr: string | null;
  slug: string | null;
  cuerpo_md: string;
};

/**
 * Snapshot mínimo del draft para diff. Reusable por todas las mutaciones
 * que necesiten saber el estado anterior.
 */
async function getSnapshot(
  medioId: string,
  draftId: string
): Promise<DraftSnapshot | null> {
  const rows = await queryAsMedio<DraftSnapshot>(
    medioId,
    `SELECT titulo, meta_title, meta_descr, slug, cuerpo_md
     FROM drafts WHERE id = $1`,
    [draftId]
  );
  return rows[0] ?? null;
}

export type MutationContext = {
  draftId: string;
  medioId: string;
  usuarioId: string;
};

export type SaveDraftResult =
  | { ok: true; diff: AuditDiff; changed: boolean }
  | { ok: false; error: string };

export async function saveDraft(
  ctx: MutationContext,
  input: SaveDraftInput
): Promise<SaveDraftResult> {
  const before = await getSnapshot(ctx.medioId, ctx.draftId);
  if (!before) return { ok: false, error: "Draft no encontrado" };

  const diff = diffDraftSnapshots(
    {
      titulo: before.titulo,
      meta_title: before.meta_title,
      meta_descr: before.meta_descr,
      slug: before.slug,
      cuerpo_md: before.cuerpo_md,
    },
    {
      titulo: input.titulo,
      meta_title: input.meta_title,
      meta_descr: input.meta_descr,
      slug: input.slug,
      cuerpo_md: input.cuerpo_md,
    }
  );

  // Sin cambios → no UPDATE, no auditoría. La UI vuelve a /bandeja igual.
  if (Object.keys(diff).length === 0) {
    return { ok: true, diff: {}, changed: false };
  }

  await queryAsMedio(
    ctx.medioId,
    `UPDATE drafts
     SET titulo = $1, meta_title = $2, meta_descr = $3, slug = $4, cuerpo_md = $5
     WHERE id = $6`,
    [
      input.titulo,
      input.meta_title,
      input.meta_descr,
      input.slug,
      input.cuerpo_md,
      ctx.draftId,
    ]
  );

  await registerAuditEvent({
    draftId: ctx.draftId,
    medioId: ctx.medioId,
    usuarioId: ctx.usuarioId,
    accion: "editado",
    diffResumen: summarizeDiff(diff),
  });

  return { ok: true, diff, changed: true };
}

export async function approveDraft(
  ctx: MutationContext
): Promise<{ ok: true } | { ok: false; error: string }> {
  // Solo se aprueba un draft que está en 'borrador'. Si ya está aprobado
  // o publicado, devolvemos error en vez de re-aprobar.
  const result = await queryAsMedio<{ estado: string }>(
    ctx.medioId,
    `UPDATE drafts SET estado = 'aprobado'
     WHERE id = $1 AND estado = 'borrador'
     RETURNING estado`,
    [ctx.draftId]
  );
  if (result.length === 0) {
    return {
      ok: false,
      error: "No se pudo aprobar: el draft no está en estado 'borrador'.",
    };
  }
  await registerAuditEvent({
    draftId: ctx.draftId,
    medioId: ctx.medioId,
    usuarioId: ctx.usuarioId,
    accion: "aprobado",
  });
  return { ok: true };
}

export async function rejectDraft(
  ctx: MutationContext,
  input: RejectDraftInput
): Promise<{ ok: true } | { ok: false; error: string }> {
  const result = await queryAsMedio<{ estado: string }>(
    ctx.medioId,
    `UPDATE drafts SET estado = 'rechazado', motivo_rechazo = $2
     WHERE id = $1 AND estado IN ('borrador', 'aprobado')
     RETURNING estado`,
    [ctx.draftId, input.motivo]
  );
  if (result.length === 0) {
    return {
      ok: false,
      error: "No se pudo rechazar: el draft no admite rechazo en su estado actual.",
    };
  }
  await registerAuditEvent({
    draftId: ctx.draftId,
    medioId: ctx.medioId,
    usuarioId: ctx.usuarioId,
    accion: "rechazado",
    notas: input.motivo,
  });
  return { ok: true };
}

export async function archiveDraft(
  ctx: MutationContext
): Promise<{ ok: true } | { ok: false; error: string }> {
  const result = await queryAsMedio<{ estado: string }>(
    ctx.medioId,
    `UPDATE drafts SET estado = 'archivado'
     WHERE id = $1 AND estado <> 'publicado'
     RETURNING estado`,
    [ctx.draftId]
  );
  if (result.length === 0) {
    return {
      ok: false,
      error: "No se pudo archivar: el draft ya está publicado.",
    };
  }
  await registerAuditEvent({
    draftId: ctx.draftId,
    medioId: ctx.medioId,
    usuarioId: ctx.usuarioId,
    accion: "archivado",
  });
  return { ok: true };
}

/**
 * Resumen del diff para `auditoria_humano.diff_resumen`. Trunca `cuerpo_md`
 * a 200 chars (before y after) para no engordar la tabla: si hace falta
 * el cuerpo íntegro, se reconstruye con el historial git del CMS.
 */
function summarizeDiff(diff: AuditDiff): AuditDiff {
  const trunc = (s: string | null) =>
    s === null ? null : s.length > 200 ? s.slice(0, 200) + "…" : s;
  const out: AuditDiff = {};
  for (const [k, v] of Object.entries(diff)) {
    if (k === "cuerpo_md") {
      out[k] = { before: trunc(v.before), after: trunc(v.after) };
    } else {
      out[k] = v;
    }
  }
  return out;
}
