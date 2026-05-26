import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EstadoBadge } from "@/components/bandeja/estado-badge";
import { ESTADOS_DRAFT } from "@/lib/drafts";

describe("EstadoBadge", () => {
  it("renderiza un label por cada estado válido", () => {
    for (const e of ESTADOS_DRAFT) {
      const { unmount } = render(<EstadoBadge estado={e} />);
      // Capitalizado (Borrador, Aprobado, …)
      const label = e.charAt(0).toUpperCase() + e.slice(1);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("aprobado y publicado usan variante 'success' (verde)", () => {
    const { container, rerender } = render(<EstadoBadge estado="aprobado" />);
    expect(container.querySelector(".bg-green-100, .bg-green-900\\/30")).not.toBeNull();
    rerender(<EstadoBadge estado="publicado" />);
    expect(container.querySelector(".bg-green-100, .bg-green-900\\/30")).not.toBeNull();
  });

  it("rechazado usa variante 'destructive' (rojo)", () => {
    const { container } = render(<EstadoBadge estado="rechazado" />);
    expect(container.querySelector(".bg-destructive")).not.toBeNull();
  });
});
