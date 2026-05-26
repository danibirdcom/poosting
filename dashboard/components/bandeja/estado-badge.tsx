import { Badge } from "@/components/ui/badge";
import type { EstadoDraft } from "@/lib/drafts-types";

/*
 * Mapeo estado-de-draft → variant de Badge + label legible.
 * Server component (sin interactividad).
 */

type Mapping = {
  variant: "default" | "secondary" | "destructive" | "outline" | "success" | "warning";
  label: string;
};

const MAPPING: Record<EstadoDraft, Mapping> = {
  borrador: { variant: "secondary", label: "Borrador" },
  aprobado: { variant: "success", label: "Aprobado" },
  publicado: { variant: "success", label: "Publicado" },
  rechazado: { variant: "destructive", label: "Rechazado" },
  programado: { variant: "outline", label: "Programado" },
  archivado: { variant: "secondary", label: "Archivado" },
};

export function EstadoBadge({ estado }: { estado: EstadoDraft }) {
  const m = MAPPING[estado] ?? { variant: "outline" as const, label: estado };
  return <Badge variant={m.variant}>{m.label}</Badge>;
}
