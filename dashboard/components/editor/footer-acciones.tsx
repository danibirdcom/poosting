"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { Archive, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  approveDraftAction,
  archiveDraftAction,
  rejectDraftAction,
  type FormResult,
} from "@/app/(app)/bandeja/[draftId]/actions";
import type { EstadoDraft } from "@/lib/drafts-types";

/*
 * Footer fijo del editor con las 4 acciones principales:
 *   - Aprobar (server action directa)
 *   - Rechazar (abre modal con textarea obligatorio)
 *   - Archivar (server action directa)
 *
 * "Guardar borrador" vive dentro del EditorForm (es submit del propio
 * form de edición). Las otras 3 acciones NO son submit del editor
 * porque queremos que ocurran sobre el estado YA persistido en BD,
 * no sobre cambios sin guardar.
 *
 * Reglas:
 *   - Solo se aprueba/rechaza desde `borrador`.
 *   - Se rechaza también desde `aprobado` (revertir aprobación).
 *   - Se archiva desde cualquier estado excepto `publicado`.
 *   - Se ocultan los botones que no aplican.
 */

type Props = {
  draftId: string;
  estado: EstadoDraft;
  motivoRechazo: string | null;
};

const INITIAL: FormResult = { ok: true };

export function FooterAcciones({ draftId, estado, motivoRechazo }: Props) {
  const [rejectOpen, setRejectOpen] = useState(false);

  const puedeAprobar = estado === "borrador";
  const puedeRechazar = estado === "borrador" || estado === "aprobado";
  const puedeArchivar = estado !== "publicado" && estado !== "archivado";

  return (
    <>
      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex max-w-[calc(100vw-14rem)] items-center justify-between gap-3 px-6 py-3">
          <div className="text-xs text-muted-foreground">
            {estado === "rechazado" && motivoRechazo ? (
              <>
                <strong>Motivo del rechazo:</strong> {motivoRechazo}
              </>
            ) : (
              <>Acciones sobre el draft</>
            )}
          </div>
          <div className="flex items-center gap-2">
            {puedeArchivar ? (
              <ConfirmActionButton
                label="Archivar"
                pendingLabel="Archivando…"
                variant="ghost"
                icon={<Archive className="h-4 w-4" />}
                confirmMessage="¿Archivar este draft? Quedará oculto pero se conserva."
                action={archiveDraftAction.bind(null, draftId)}
              />
            ) : null}
            {puedeRechazar ? (
              <Button
                type="button"
                variant="outline"
                className="gap-1"
                onClick={() => setRejectOpen(true)}
              >
                <X className="h-4 w-4" />
                Rechazar
              </Button>
            ) : null}
            {puedeAprobar ? (
              <ConfirmActionButton
                label="Aprobar"
                pendingLabel="Aprobando…"
                variant="default"
                icon={<Check className="h-4 w-4" />}
                confirmMessage="¿Aprobar este draft? Pasará a estado 'aprobado'."
                action={approveDraftAction.bind(null, draftId)}
              />
            ) : null}
          </div>
        </div>
      </div>

      <RejectDialog
        draftId={draftId}
        open={rejectOpen}
        onOpenChange={setRejectOpen}
      />
    </>
  );
}

function ConfirmActionButton({
  label,
  pendingLabel,
  icon,
  variant,
  confirmMessage,
  action,
}: {
  label: string;
  pendingLabel: string;
  icon: React.ReactNode;
  variant: "default" | "ghost" | "outline" | "destructive" | "secondary";
  confirmMessage: string;
  action: () => Promise<void>;
}) {
  return (
    <form
      action={action}
      onSubmit={(e) => {
        if (!window.confirm(confirmMessage)) {
          e.preventDefault();
        }
      }}
    >
      <ConfirmButton label={label} pendingLabel={pendingLabel} variant={variant} icon={icon} />
    </form>
  );
}

function ConfirmButton({
  label,
  pendingLabel,
  variant,
  icon,
}: {
  label: string;
  pendingLabel: string;
  variant: "default" | "ghost" | "outline" | "destructive" | "secondary";
  icon: React.ReactNode;
}) {
  const status = useFormStatus();
  return (
    <Button type="submit" variant={variant} className="gap-1" disabled={status.pending}>
      {icon}
      {status.pending ? pendingLabel : label}
    </Button>
  );
}

function RejectDialog({
  draftId,
  open,
  onOpenChange,
}: {
  draftId: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [state, formAction] = useActionState(
    rejectDraftAction.bind(null, draftId),
    INITIAL
  );
  const [motivo, setMotivo] = useState("");
  const tooShort = motivo.trim().length < 10;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rechazar draft</DialogTitle>
          <DialogDescription>
            El motivo se guarda en `auditoria_humano` y en `drafts.motivo_rechazo`.
            Sé concreto: ayuda al redactor y al feedback loop.
          </DialogDescription>
        </DialogHeader>
        <form action={formAction} className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="motivo">Motivo (mínimo 10 caracteres)</Label>
            <Textarea
              id="motivo"
              name="motivo"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              rows={4}
              required
              minLength={10}
              maxLength={1000}
              placeholder="Ej.: dos fuentes son blogs sin verificación; reescribir lead."
            />
            <p className="text-xs text-muted-foreground">
              {motivo.trim().length} / 1000 caracteres
            </p>
          </div>
          {!state.ok ? (
            <p role="alert" className="text-sm text-destructive">
              {state.error}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <RejectSubmit disabled={tooShort} />
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RejectSubmit({ disabled }: { disabled: boolean }) {
  const status = useFormStatus();
  return (
    <Button type="submit" variant="destructive" disabled={disabled || status.pending}>
      {status.pending ? "Rechazando…" : "Rechazar draft"}
    </Button>
  );
}
