import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Helper estándar de shadcn/ui para componer clases de Tailwind
 * (soporta condicionales + merge de utilidades conflictivas).
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
