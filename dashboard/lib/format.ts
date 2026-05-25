import { formatDistanceToNow, format } from "date-fns";
import { es } from "date-fns/locale";

/**
 * "hace 2 horas", "hace 3 días". Locale ES.
 * Acepta Date | string ISO | null. Devuelve "—" si null.
 */
export function formatRelativeDate(value: Date | string | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "—";
  return formatDistanceToNow(date, { addSuffix: true, locale: es });
}

/**
 * "24 may 2026, 19:42". Para mostrar en tooltip al hacer hover sobre la
 * fecha relativa.
 */
export function formatAbsoluteDate(value: Date | string | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "—";
  return format(date, "d MMM yyyy, HH:mm", { locale: es });
}

/**
 * Trunca un string a `max` chars, añadiendo "…" si se cortó.
 */
export function truncate(s: string | null | undefined, max: number): string {
  if (!s) return "";
  if (s.length <= max) return s;
  return s.slice(0, max - 1).trimEnd() + "…";
}
