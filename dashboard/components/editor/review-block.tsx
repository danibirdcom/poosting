import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import type { ReviewOutput } from "@/lib/draft-detail";

type Props = {
  review: ReviewOutput | null;
};

/*
 * Bloque de errores + sugerencias del nodo `review`.
 *
 * Si no hay review run (caso raro: pipeline abortó antes), mostramos
 * un placeholder neutro. Los errores tienen tono destructivo, las
 * sugerencias informativo. No incluimos checkboxes "descartar" en PR2
 * (no hay tabla persistente para ello); si el editor decide aprobar
 * pese a errores, lo hace y la auditoría lo registra.
 */
export function ReviewBlock({ review }: Props) {
  if (!review) {
    return (
      <section className="rounded-lg border border-border bg-card p-3">
        <h2 className="mb-2 text-sm font-semibold">Revisión automática</h2>
        <p className="text-xs text-muted-foreground">
          No hay output del nodo review (el run pudo abortar antes).
        </p>
      </section>
    );
  }

  const { aprobado, errores, sugerencias, requiereRevisionHumana } = review;

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <header className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Revisión automática</h2>
        {aprobado ? (
          <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" /> aprobado
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
            <AlertCircle className="h-3.5 w-3.5" />
            {requiereRevisionHumana ? "requiere revisión" : "con errores"}
          </span>
        )}
      </header>

      {errores.length > 0 ? (
        <div className="mb-3 space-y-1">
          <h3 className="text-xs font-medium uppercase tracking-wider text-destructive">
            Errores ({errores.length})
          </h3>
          <ul className="space-y-1 text-xs">
            {errores.map((e, i) => (
              <li
                key={i}
                className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-foreground"
              >
                {e}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {sugerencias.length > 0 ? (
        <div className="space-y-1">
          <h3 className="flex items-center gap-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            <Info className="h-3 w-3" /> Sugerencias ({sugerencias.length})
          </h3>
          <ul className="space-y-1 text-xs">
            {sugerencias.map((s, i) => (
              <li
                key={i}
                className="rounded-md border border-border bg-muted/40 px-2 py-1"
              >
                {s}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {errores.length === 0 && sugerencias.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Sin errores ni sugerencias.
        </p>
      ) : null}
    </section>
  );
}
