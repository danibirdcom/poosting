import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DraftsTable } from "@/components/bandeja/drafts-table";
import type { DraftRow } from "@/lib/drafts";

function makeRow(over: Partial<DraftRow> = {}): DraftRow {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    titulo: "Zaragoza Florece bate récord en su edición 2026",
    estado: "borrador",
    creadoAt: new Date("2026-05-24T17:42:00Z"),
    redactorNombre: "María García",
    requiereRevision: false,
    nErrores: 0,
    ...over,
  };
}

describe("DraftsTable", () => {
  it("muestra empty state cuando no hay filas", () => {
    render(<DraftsTable rows={[]} />);
    expect(screen.getByText(/aún no hay drafts/i)).toBeInTheDocument();
  });

  it("renderiza una fila por draft con título y redactor", () => {
    render(
      <DraftsTable
        rows={[
          makeRow(),
          makeRow({
            id: "00000000-0000-0000-0000-000000000002",
            titulo: "Otro draft",
            redactorNombre: "Pepe",
          }),
        ]}
      />
    );
    expect(screen.getAllByTestId("draft-row")).toHaveLength(2);
    expect(screen.getByText(/Zaragoza Florece/)).toBeInTheDocument();
    expect(screen.getByText("Pepe")).toBeInTheDocument();
  });

  it("muestra badge de revisión y nº de errores", () => {
    render(
      <DraftsTable
        rows={[makeRow({ requiereRevision: true, nErrores: 3 })]}
      />
    );
    // El header de columna también dice "Revisión" → filtramos por el
    // badge (no es un <th>, es el span dentro del Badge).
    const badges = screen.getAllByText(/revisión/i);
    expect(badges.some((el) => el.closest("th") === null)).toBe(true);
    expect(screen.getByText(/3 errores/)).toBeInTheDocument();
  });

  it("trunca títulos largos con elipsis (a 80 chars)", () => {
    const longTitle = "x".repeat(120);
    render(<DraftsTable rows={[makeRow({ titulo: longTitle })]} />);
    // El span del td contiene el truncado; el title atributo tiene el original.
    const cell = screen.getByTitle(longTitle);
    expect(cell.textContent?.length).toBeLessThan(longTitle.length);
    expect(cell.textContent).toMatch(/…$/);
  });

  it("muestra '—' cuando no hay redactor", () => {
    render(<DraftsTable rows={[makeRow({ redactorNombre: null })]} />);
    const cells = screen.getAllByText("—");
    expect(cells.length).toBeGreaterThan(0);
  });

  it("genera enlace 'Ver' a /bandeja/[draftId]", () => {
    render(<DraftsTable rows={[makeRow({ id: "abc-123" })]} />);
    const link = screen.getByRole("link", { name: /ver/i });
    expect(link.getAttribute("href")).toBe("/bandeja/abc-123");
  });
});
