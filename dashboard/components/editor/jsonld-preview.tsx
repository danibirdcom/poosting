"use client";

import { useState } from "react";
import { Check, ChevronDown, ChevronUp, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";

type Props = {
  schemaJsonld: unknown | null;
};

export function JsonLdPreview({ schemaJsonld }: Props) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!schemaJsonld) {
    return (
      <section className="rounded-lg border border-border bg-card p-3">
        <h2 className="mb-2 text-sm font-semibold">JSON-LD</h2>
        <p className="text-xs text-muted-foreground">
          Sin schema.org generado todavía (entra en el nodo enrich).
        </p>
      </section>
    );
  }

  const json = JSON.stringify(schemaJsonld, null, 2);

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <header className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">JSON-LD</h2>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 text-xs"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(json);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              } catch {
                // ignora; el usuario puede seleccionar manualmente
              }
            }}
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copiado" : "Copiar"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 text-xs"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? (
              <>
                <ChevronUp className="h-3 w-3" /> Plegar
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" /> Ver
              </>
            )}
          </Button>
        </div>
      </header>
      {open ? (
        <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/30 p-2 font-mono text-[11px] leading-tight">
          {json}
        </pre>
      ) : (
        <p className="text-xs text-muted-foreground">
          {json.length} chars · click en &ldquo;Ver&rdquo; para inspeccionar.
        </p>
      )}
    </section>
  );
}
