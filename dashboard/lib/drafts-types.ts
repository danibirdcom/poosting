/*
 * Tipos y constantes de drafts puros (sin acceso a BD).
 *
 * Vive en su propio módulo para que los Client Components (p. ej.
 * `components/bandeja/filters.tsx`) puedan importar los enums sin
 * arrastrar `pg` al bundle del navegador. `lib/drafts.ts` re-exporta
 * estos símbolos y añade las funciones que sí tocan la BD.
 */

export const ESTADOS_DRAFT = [
  "borrador",
  "aprobado",
  "publicado",
  "rechazado",
  "programado",
  "archivado",
] as const;

export type EstadoDraft = (typeof ESTADOS_DRAFT)[number];

export const ORDENES_DRAFT = ["reciente", "antiguo", "titulo"] as const;
export type OrdenDraft = (typeof ORDENES_DRAFT)[number];

export const PAGE_SIZE = 20;

export type DraftRow = {
  id: string;
  titulo: string;
  estado: EstadoDraft;
  creadoAt: Date;
  redactorNombre: string | null;
  requiereRevision: boolean;
  nErrores: number;
};

export type DraftFilters = {
  estados?: EstadoDraft[]; // vacío/undefined → todos
  q?: string;              // búsqueda ILIKE en titulo
  orden?: OrdenDraft;      // default 'reciente'
  page?: number;           // 1-based
};
