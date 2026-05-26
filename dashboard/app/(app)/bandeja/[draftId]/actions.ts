"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { requireSession } from "@/lib/auth-utils";
import {
  approveDraft,
  archiveDraft,
  RejectDraftSchema,
  rejectDraft,
  SaveDraftSchema,
  saveDraft,
} from "@/lib/drafts-update";

/*
 * Server Actions del editor de draft.
 *
 * Patrón común:
 *   1. requireSession() → garantiza sesión válida + extrae medioId + usuarioId.
 *   2. zod parse del FormData.
 *   3. delegar en lib/drafts-update.
 *   4. revalidatePath + redirect (en aprobar/rechazar/archivar) o
 *      revalidatePath sin redirect (en guardar) — el editor se queda
 *      abierto tras un save.
 *
 * Si el zod parse falla, devolvemos un FormResult con error inline.
 * Si la mutación falla, también.
 */

export type FormResult =
  | { ok: true; message?: string }
  | { ok: false; error: string };

export async function saveDraftAction(
  draftId: string,
  _prev: FormResult | undefined,
  formData: FormData
): Promise<FormResult> {
  const session = await requireSession();

  const parsed = SaveDraftSchema.safeParse({
    titulo: formData.get("titulo"),
    meta_title: emptyToNull(formData.get("meta_title")),
    meta_descr: emptyToNull(formData.get("meta_descr")),
    slug: emptyToNull(formData.get("slug")),
    cuerpo_md: formData.get("cuerpo_md"),
  });
  if (!parsed.success) {
    return { ok: false, error: firstError(parsed.error) };
  }

  const result = await saveDraft(
    {
      draftId,
      medioId: session.user.medioId,
      usuarioId: session.user.id,
    },
    parsed.data
  );
  if (!result.ok) return { ok: false, error: result.error };

  revalidatePath(`/bandeja/${draftId}`);
  revalidatePath("/bandeja");
  return result.changed
    ? { ok: true, message: "Cambios guardados." }
    : { ok: true, message: "Sin cambios." };
}

export async function approveDraftAction(draftId: string): Promise<void> {
  const session = await requireSession();
  const result = await approveDraft({
    draftId,
    medioId: session.user.medioId,
    usuarioId: session.user.id,
  });
  if (!result.ok) {
    // No tenemos canal de error para botón directo: dejamos un throw que
    // Next renderiza como error.tsx. La UI puede luego ofrecer reintento.
    throw new Error(result.error);
  }
  revalidatePath("/bandeja");
  revalidatePath(`/bandeja/${draftId}`);
  redirect("/bandeja");
}

export async function rejectDraftAction(
  draftId: string,
  _prev: FormResult | undefined,
  formData: FormData
): Promise<FormResult> {
  const session = await requireSession();
  const parsed = RejectDraftSchema.safeParse({
    motivo: formData.get("motivo"),
  });
  if (!parsed.success) {
    return { ok: false, error: firstError(parsed.error) };
  }
  const result = await rejectDraft(
    {
      draftId,
      medioId: session.user.medioId,
      usuarioId: session.user.id,
    },
    parsed.data
  );
  if (!result.ok) return { ok: false, error: result.error };

  revalidatePath("/bandeja");
  revalidatePath(`/bandeja/${draftId}`);
  redirect("/bandeja");
}

export async function archiveDraftAction(draftId: string): Promise<void> {
  const session = await requireSession();
  const result = await archiveDraft({
    draftId,
    medioId: session.user.medioId,
    usuarioId: session.user.id,
  });
  if (!result.ok) {
    throw new Error(result.error);
  }
  revalidatePath("/bandeja");
  revalidatePath(`/bandeja/${draftId}`);
  redirect("/bandeja");
}

function emptyToNull(v: FormDataEntryValue | null): string | null {
  if (v === null) return null;
  const s = typeof v === "string" ? v : "";
  return s.trim() === "" ? null : s;
}

function firstError(err: { issues: { path: (string | number)[]; message: string }[] }): string {
  const issue = err.issues[0];
  if (!issue) return "Datos inválidos";
  const field = issue.path.join(".");
  return field ? `${field}: ${issue.message}` : issue.message;
}
