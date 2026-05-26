import { queryAsMedio } from "@/lib/db";

/*
 * Helpers para escribir en `auditoria_humano`. La UI es la única
 * escritora de esta tabla (workers nunca); el GRANT está en migración
 * 007 (SELECT + INSERT para redactia_web).
 *
 * Toda inserción debe llevar:
 *   - draft_id: a qué draft se refiere.
 *   - medio_id: redundante con RLS pero NOT NULL en la tabla.
 *   - usuario_id: quién hizo la acción (UUID del usuario logueado).
 *   - accion: aprobado | rechazado | editado | archivado.
 *   - notas: motivo libre (obligatorio en rechazo, opcional en otros).
 *   - diff_resumen: JSON {campo: {before, after}} solo cuando hay edición.
 */

export type AuditAction = "aprobado" | "rechazado" | "editado" | "archivado";

export type AuditFieldDiff = {
  before: string | null;
  after: string | null;
};

export type AuditDiff = Record<string, AuditFieldDiff>;

export type AuditEvent = {
  draftId: string;
  medioId: string;
  usuarioId: string;
  accion: AuditAction;
  notas?: string | null;
  diffResumen?: AuditDiff | null;
};

/**
 * Registra una acción humana sobre un draft. Sin transacción explícita:
 * el caller (server action) ya envuelve UPDATE + INSERT en una unidad
 * lógica; si falla este INSERT, la respuesta error revierte el flujo
 * desde el punto de vista del usuario. Para atomicidad real BD-side
 * habría que usar un client del pool (futuro PR si hace falta).
 */
export async function registerAuditEvent(event: AuditEvent): Promise<void> {
  const { draftId, medioId, usuarioId, accion } = event;
  const notas = event.notas ?? null;
  // JSONB acepta null directamente; si pasamos undefined `pg` lo convierte
  // a NULL, pero somos explícitos.
  const diff = event.diffResumen
    ? JSON.stringify(event.diffResumen)
    : null;
  await queryAsMedio(
    medioId,
    `INSERT INTO auditoria_humano
       (draft_id, medio_id, usuario_id, accion, notas, diff_resumen)
     VALUES ($1, $2, $3, $4, $5, $6::jsonb)`,
    [draftId, medioId, usuarioId, accion, notas, diff]
  );
}

/**
 * Calcula el diff entre dos snapshots del mismo draft. Solo incluye los
 * campos que cambiaron. Útil para el `diff_resumen` de `editado`.
 *
 * No exportamos las claves que no aparecen en `after` (campos no editados).
 */
export function diffDraftSnapshots(
  before: Record<string, string | null>,
  after: Record<string, string | null>
): AuditDiff {
  const diff: AuditDiff = {};
  for (const key of Object.keys(after)) {
    const b = before[key] ?? null;
    const a = after[key] ?? null;
    if (b !== a) {
      diff[key] = { before: b, after: a };
    }
  }
  return diff;
}
