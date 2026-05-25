import { describe, it, expect } from "vitest";
import { truncate, formatAbsoluteDate } from "@/lib/format";

describe("truncate", () => {
  it("devuelve el string entero si está dentro del límite", () => {
    expect(truncate("hola mundo", 50)).toBe("hola mundo");
  });

  it("trunca con elipsis si supera el límite", () => {
    expect(truncate("hola mundo", 5)).toBe("hola…");
  });

  it("maneja null y undefined", () => {
    expect(truncate(null, 10)).toBe("");
    expect(truncate(undefined, 10)).toBe("");
  });
});

describe("formatAbsoluteDate", () => {
  it("formatea una fecha ISO en español", () => {
    // Mes "may" en es. Comprobamos contiene el mes (sin asumir zona horaria).
    const out = formatAbsoluteDate("2026-05-24T17:42:00Z");
    expect(out).toMatch(/may 2026/);
  });

  it("devuelve '—' para null", () => {
    expect(formatAbsoluteDate(null)).toBe("—");
  });

  it("devuelve '—' para fecha inválida", () => {
    expect(formatAbsoluteDate("no-es-fecha")).toBe("—");
  });
});
