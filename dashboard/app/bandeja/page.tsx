import Link from "next/link";
import type { Route } from "next";
import { Filters } from "@/components/bandeja/filters";
import { DraftsTable } from "@/components/bandeja/drafts-table";
import {
  countDrafts,
  listDrafts,
  PAGE_SIZE,
  type EstadoDraft,
  type OrdenDraft,
  ESTADOS_DRAFT,
  ORDENES_DRAFT,
} from "@/lib/drafts";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/*
 * Bandeja de drafts (Server Component).
 *
 * Lee filtros de searchParams, fetchea desde Postgres con RLS via
 * `queryAsMedio`, y renderiza tabla + paginación. Cualquier cambio en
 * filtros desde el cliente reescribe la URL → este Server Component
 * se re-renderiza con los datos nuevos.
 *
 * `medioId` viene de `MEDIO_ID_HARDCODED` (PR1). En PR2 viene de la
 * sesión NextAuth.
 */

export const dynamic = "force-dynamic"; // depende de searchParams + BD

type SearchParams = {
  q?: string;
  estado?: string;
  orden?: string;
  page?: string;
};

function parseFiltros(sp: SearchParams) {
  const estados = (sp.estado ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter((s): s is EstadoDraft =>
      (ESTADOS_DRAFT as readonly string[]).includes(s)
    );
  const ordenRaw = sp.orden;
  const orden: OrdenDraft = (ORDENES_DRAFT as readonly string[]).includes(
    ordenRaw ?? ""
  )
    ? (ordenRaw as OrdenDraft)
    : "reciente";
  const page = Math.max(1, parseInt(sp.page ?? "1", 10) || 1);
  return {
    estados: estados.length > 0 ? estados : undefined,
    q: sp.q,
    orden,
    page,
  };
}

function getMedioId(): string {
  const id = process.env.MEDIO_ID_HARDCODED;
  if (!id) {
    throw new Error(
      "MEDIO_ID_HARDCODED no definido. PR1 lee el medio activo desde esta env var; copia .env.local.example a .env.local."
    );
  }
  return id;
}

export default async function BandejaPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const filtros = parseFiltros(sp);
  const medioId = getMedioId();

  const [rows, total] = await Promise.all([
    listDrafts(medioId, filtros),
    countDrafts(medioId, filtros),
  ]);

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            Bandeja de drafts
          </h1>
          <Badge variant="secondary">{total}</Badge>
        </div>
      </div>

      <Filters />

      <DraftsTable rows={rows} />

      {lastPage > 1 ? (
        <Pagination
          page={filtros.page}
          lastPage={lastPage}
          searchParams={sp}
        />
      ) : null}
    </div>
  );
}

function Pagination({
  page,
  lastPage,
  searchParams,
}: {
  page: number;
  lastPage: number;
  searchParams: SearchParams;
}) {
  function hrefFor(p: number): Route {
    const sp = new URLSearchParams();
    if (searchParams.q) sp.set("q", searchParams.q);
    if (searchParams.estado) sp.set("estado", searchParams.estado);
    if (searchParams.orden) sp.set("orden", searchParams.orden);
    if (p > 1) sp.set("page", String(p));
    const qs = sp.toString();
    return (qs ? `/bandeja?${qs}` : "/bandeja") as Route;
  }

  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">
        Página {page} de {lastPage}
      </span>
      <div className="flex items-center gap-2">
        <Link
          href={hrefFor(Math.max(1, page - 1))}
          className={cn(
            "h-8 rounded-md border border-border px-3 leading-8 hover:bg-accent",
            page <= 1 && "pointer-events-none opacity-50"
          )}
          aria-disabled={page <= 1}
        >
          ←
        </Link>
        <Link
          href={hrefFor(Math.min(lastPage, page + 1))}
          className={cn(
            "h-8 rounded-md border border-border px-3 leading-8 hover:bg-accent",
            page >= lastPage && "pointer-events-none opacity-50"
          )}
          aria-disabled={page >= lastPage}
        >
          →
        </Link>
      </div>
    </div>
  );
}
