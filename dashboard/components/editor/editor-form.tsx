"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { saveDraftAction, type FormResult } from "@/app/(app)/bandeja/[draftId]/actions";
import type { DraftDetail } from "@/lib/draft-detail";

/*
 * Formulario editable del draft.
 *
 * - Estado controlado: titulo, meta_title, meta_descr, slug, cuerpo_md.
 * - Contadores de caracteres para meta_title (recomendado 50-60) y
 *   meta_descr (recomendado 140-160).
 * - Server Action `saveDraftAction` bindeada al draftId.
 * - useActionState para mostrar mensaje de éxito o error inline.
 */

type Props = {
  draft: DraftDetail;
};

const INITIAL: FormResult = { ok: true, message: "" };

const META_TITLE_OPTIMAL_MIN = 50;
const META_TITLE_OPTIMAL_MAX = 60;
const META_DESCR_OPTIMAL_MIN = 140;
const META_DESCR_OPTIMAL_MAX = 160;

export function EditorForm({ draft }: Props) {
  const [state, formAction] = useActionState(
    saveDraftAction.bind(null, draft.id),
    INITIAL
  );

  const [titulo, setTitulo] = useState(draft.titulo);
  const [metaTitle, setMetaTitle] = useState(draft.metaTitle ?? "");
  const [metaDescr, setMetaDescr] = useState(draft.metaDescr ?? "");
  const [slug, setSlug] = useState(draft.slug ?? "");
  const [cuerpo, setCuerpo] = useState(draft.cuerpoMd);

  return (
    <form action={formAction} className="space-y-4 rounded-lg border border-border bg-card p-4">
      <div className="space-y-2">
        <Label htmlFor="titulo">Título (H1)</Label>
        <Input
          id="titulo"
          name="titulo"
          value={titulo}
          onChange={(e) => setTitulo(e.target.value)}
          required
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="meta_title">Meta title</Label>
            <Counter
              len={metaTitle.length}
              min={META_TITLE_OPTIMAL_MIN}
              max={META_TITLE_OPTIMAL_MAX}
            />
          </div>
          <Input
            id="meta_title"
            name="meta_title"
            value={metaTitle}
            onChange={(e) => setMetaTitle(e.target.value)}
            placeholder="Diferente del H1 (Discover lo agradece)"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="slug">Slug</Label>
          <Input
            id="slug"
            name="slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
            pattern="[a-z0-9-]+"
            placeholder="kebab-case-sin-stopwords"
          />
          <p className="text-xs text-muted-foreground">
            Solo minúsculas, dígitos y guiones.
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="meta_descr">Meta description</Label>
          <Counter
            len={metaDescr.length}
            min={META_DESCR_OPTIMAL_MIN}
            max={META_DESCR_OPTIMAL_MAX}
          />
        </div>
        <Textarea
          id="meta_descr"
          name="meta_descr"
          value={metaDescr}
          onChange={(e) => setMetaDescr(e.target.value)}
          rows={2}
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="cuerpo_md">Cuerpo (Markdown)</Label>
          <span className="text-xs text-muted-foreground">
            {wordCount(cuerpo)} palabras
          </span>
        </div>
        <Textarea
          id="cuerpo_md"
          name="cuerpo_md"
          value={cuerpo}
          onChange={(e) => setCuerpo(e.target.value)}
          rows={20}
          className="font-mono text-sm"
        />
      </div>

      <FormFooter state={state} />
    </form>
  );
}

function FormFooter({ state }: { state: FormResult }) {
  const status = useFormStatus();
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="text-sm">
        {state.ok && state.message ? (
          <span className="text-emerald-600 dark:text-emerald-400">
            {state.message}
          </span>
        ) : null}
        {!state.ok ? (
          <span role="alert" className="text-destructive">
            {state.error}
          </span>
        ) : null}
      </div>
      <Button type="submit" variant="secondary" disabled={status.pending}>
        {status.pending ? "Guardando…" : "Guardar borrador"}
      </Button>
    </div>
  );
}

function Counter({ len, min, max }: { len: number; min: number; max: number }) {
  const optimal = len >= min && len <= max;
  const tone = optimal
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-muted-foreground";
  return (
    <span className={`text-xs ${tone}`} aria-live="polite">
      {len} ({min}-{max})
    </span>
  );
}

function wordCount(s: string): number {
  return s.trim().split(/\s+/).filter(Boolean).length;
}
