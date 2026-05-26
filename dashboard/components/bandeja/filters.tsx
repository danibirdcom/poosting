"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import {
  ESTADOS_DRAFT,
  ORDENES_DRAFT,
  type EstadoDraft,
  type OrdenDraft,
} from "@/lib/drafts-types";
import { cn } from "@/lib/utils";

/*
 * Filtros de la bandeja. El estado vive en la URL (searchParams) para que
 * sea bookmarkeable y compartible. Tres controles:
 *   - q: búsqueda por título (debounce 300ms).
 *   - estados: checkboxes inline (vacío = todos).
 *   - orden: select nativo (reciente | antiguo | titulo).
 *
 * Cualquier cambio reescribe los searchParams y dispara router.push, lo
 * que re-renderiza el Server Component padre (bandeja/page.tsx) con los
 * nuevos drafts. `useTransition` evita parpadeo y permite mostrar estado
 * "actualizando" si quisiéramos (no lo usamos en PR1).
 */

const ETIQUETAS_ESTADO: Record<EstadoDraft, string> = {
  borrador: "Borrador",
  aprobado: "Aprobado",
  publicado: "Publicado",
  rechazado: "Rechazado",
  programado: "Programado",
  archivado: "Archivado",
};

const ETIQUETAS_ORDEN: Record<OrdenDraft, string> = {
  reciente: "Más recientes",
  antiguo: "Más antiguos",
  titulo: "Título A–Z",
};

export function Filters() {
  const router = useRouter();
  const sp = useSearchParams();
  const [, startTransition] = useTransition();

  const qFromUrl = sp.get("q") ?? "";
  const [qLocal, setQLocal] = useState(qFromUrl);
  const qDebounce = useRef<NodeJS.Timeout | null>(null);

  // Si la URL cambia desde fuera (back/forward), sincroniza el input.
  useEffect(() => {
    setQLocal(qFromUrl);
  }, [qFromUrl]);

  const estadosSeleccionados = new Set(
    (sp.get("estado") ?? "")
      .split(",")
      .filter((s): s is EstadoDraft =>
        (ESTADOS_DRAFT as readonly string[]).includes(s)
      )
  );
  const orden = (sp.get("orden") as OrdenDraft) ?? "reciente";

  function pushParams(updater: (p: URLSearchParams) => void) {
    const next = new URLSearchParams(sp.toString());
    updater(next);
    next.delete("page"); // cualquier cambio de filtro vuelve a página 1
    startTransition(() => {
      router.push(`/bandeja?${next.toString()}`);
    });
  }

  function onQChange(v: string) {
    setQLocal(v);
    if (qDebounce.current) clearTimeout(qDebounce.current);
    qDebounce.current = setTimeout(() => {
      pushParams((p) => {
        if (v.trim()) p.set("q", v.trim());
        else p.delete("q");
      });
    }, 300);
  }

  function toggleEstado(e: EstadoDraft) {
    const next = new Set(estadosSeleccionados);
    if (next.has(e)) next.delete(e);
    else next.add(e);
    pushParams((p) => {
      if (next.size === 0) p.delete("estado");
      else p.set("estado", Array.from(next).join(","));
    });
  }

  function changeOrden(v: OrdenDraft) {
    pushParams((p) => {
      if (v === "reciente") p.delete("orden");
      else p.set("orden", v);
    });
  }

  return (
    <div className="space-y-3" data-testid="filters">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          placeholder="Buscar por título…"
          value={qLocal}
          onChange={(e) => onQChange(e.target.value)}
          className="h-9 w-64 rounded-md border border-input bg-background px-3 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          Ordenar por
          <select
            value={orden}
            onChange={(e) => changeOrden(e.target.value as OrdenDraft)}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {ORDENES_DRAFT.map((o) => (
              <option key={o} value={o}>
                {ETIQUETAS_ORDEN[o]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wider text-muted-foreground">
          Estado:
        </span>
        {ESTADOS_DRAFT.map((e) => {
          const active = estadosSeleccionados.has(e);
          return (
            <button
              key={e}
              type="button"
              onClick={() => toggleEstado(e)}
              aria-pressed={active}
              className={cn(
                "h-7 rounded-md border px-3 text-xs transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-input bg-background text-foreground hover:bg-accent"
              )}
            >
              {ETIQUETAS_ESTADO[e]}
            </button>
          );
        })}
        {estadosSeleccionados.size > 0 ? (
          <button
            type="button"
            onClick={() => pushParams((p) => p.delete("estado"))}
            className="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            limpiar
          </button>
        ) : null}
      </div>
    </div>
  );
}
