/*
 * Bandeja de drafts (Server Component).
 *
 * PR1 commit 1: placeholder. La query real + tabla de drafts entra en el
 * commit 2 una vez confirmado el scaffolding. Razón: el spec original
 * asumía columnas en `drafts` que no existen (review_errores,
 * requiere_revision_humana, redactor_id), y esas se derivan via JOIN
 * con `run_steps` — eso requiere SQL no trivial que merece su propio
 * commit revisable.
 */

export default function BandejaPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Bandeja de drafts</h1>
      </div>
      <div className="rounded-lg border border-dashed border-border bg-muted/30 p-12 text-center">
        <p className="text-sm text-muted-foreground">
          La tabla de drafts se implementa en el siguiente commit (PR1 commit 2).
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          Este commit incluye scaffolding base + migraciones 006/007.
        </p>
      </div>
    </div>
  );
}
