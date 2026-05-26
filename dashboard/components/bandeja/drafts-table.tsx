import Link from "next/link";
import type { Route } from "next";
import { AlertCircle } from "lucide-react";
import type { DraftRow } from "@/lib/drafts-types";
import { Badge } from "@/components/ui/badge";
import { EstadoBadge } from "@/components/bandeja/estado-badge";
import { formatAbsoluteDate, formatRelativeDate, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

/*
 * Tabla de drafts (Server Component — renderiza props).
 *
 * Columnas:
 *   1. Fecha (relativa, tooltip nativo con absoluta vía `title`).
 *   2. Título (truncado a 80 chars + tooltip).
 *   3. Redactor.
 *   4. Estado (Badge).
 *   5. Revisión pendiente + nº errores (badges, solo si > 0).
 *   6. Acción: enlace "Ver" a /bandeja/[draftId].
 *
 * Empty state si rows.length === 0.
 */

export function DraftsTable({ rows }: { rows: DraftRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/30 p-12 text-center">
        <p className="text-sm text-muted-foreground">
          Aún no hay drafts en la bandeja.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-4 py-3 font-medium">Fecha</th>
            <th className="px-4 py-3 font-medium">Título</th>
            <th className="px-4 py-3 font-medium">Redactor</th>
            <th className="px-4 py-3 font-medium">Estado</th>
            <th className="px-4 py-3 font-medium">Revisión</th>
            <th className="px-4 py-3 font-medium text-right" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={row.id}
              data-testid="draft-row"
              className={cn(
                "border-b border-border last:border-b-0",
                idx % 2 === 1 ? "bg-muted/20" : undefined
              )}
            >
              <td
                className="whitespace-nowrap px-4 py-3 text-muted-foreground"
                title={formatAbsoluteDate(row.creadoAt)}
              >
                {formatRelativeDate(row.creadoAt)}
              </td>
              <td className="px-4 py-3" title={row.titulo}>
                {truncate(row.titulo, 80)}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                {row.redactorNombre ?? "—"}
              </td>
              <td className="px-4 py-3">
                <EstadoBadge estado={row.estado} />
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-1">
                  {row.requiereRevision ? (
                    <Badge variant="warning" className="gap-1">
                      <AlertCircle className="h-3 w-3" />
                      revisión
                    </Badge>
                  ) : null}
                  {row.nErrores > 0 ? (
                    <Badge variant="destructive">{row.nErrores} errores</Badge>
                  ) : null}
                  {!row.requiereRevision && row.nErrores === 0 ? (
                    <span className="text-xs text-muted-foreground">—</span>
                  ) : null}
                </div>
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-right">
                <Link
                  href={`/bandeja/${row.id}` as Route}
                  className="text-xs font-medium text-primary underline-offset-4 hover:underline"
                >
                  Ver →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
