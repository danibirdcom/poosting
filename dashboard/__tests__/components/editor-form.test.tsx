import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Mock de la server action: useActionState la invoca con un FormData,
// devolvemos un noop que no toca BD ni red.
vi.mock("@/app/(app)/bandeja/[draftId]/actions", () => ({
  saveDraftAction: async () => ({ ok: true, message: "" }),
}));

import { EditorForm } from "@/components/editor/editor-form";
import type { DraftDetail } from "@/lib/draft-detail";

function makeDraft(over: Partial<DraftDetail> = {}): DraftDetail {
  return {
    id: "d1",
    runId: "r1",
    titulo: "Título inicial",
    metaTitle: "Meta inicial con cierta longitud razonable",
    metaDescr:
      "Descripción muy corta",
    slug: "slug-inicial",
    cuerpoMd: "Lorem ipsum dolor sit amet ".repeat(20),
    schemaJsonld: null,
    estado: "borrador",
    motivoRechazo: null,
    creadoAt: new Date(),
    imagenDestacada: null,
    redactor: null,
    ...over,
  };
}

describe("EditorForm", () => {
  it("renderiza los 5 campos del draft", () => {
    render(<EditorForm draft={makeDraft()} />);
    expect(screen.getByLabelText(/Título/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Meta title/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Meta description/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Slug/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Cuerpo/)).toBeInTheDocument();
  });

  it("fuerza el slug a minúsculas al escribir", () => {
    render(<EditorForm draft={makeDraft({ slug: "" })} />);
    const slug = screen.getByLabelText(/Slug/) as HTMLInputElement;
    fireEvent.change(slug, { target: { value: "MAYUS-Con-Acentos" } });
    expect(slug.value).toBe("mayus-con-acentos");
  });

  it("muestra contador de meta_title", () => {
    render(<EditorForm draft={makeDraft({ metaTitle: "x".repeat(45) })} />);
    expect(screen.getByText(/45 \(50-60\)/)).toBeInTheDocument();
  });

  it("muestra word count del cuerpo", () => {
    render(<EditorForm draft={makeDraft({ cuerpoMd: "uno dos tres cuatro" })} />);
    expect(screen.getByText(/4 palabras/)).toBeInTheDocument();
  });
});
