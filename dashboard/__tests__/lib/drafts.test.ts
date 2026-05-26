import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock del módulo de BD: capturamos los params que listDrafts/countDrafts
// pasan a queryAsMedio para verificar la normalización de filtros.
const queryAsMedio = vi.fn();
vi.mock("@/lib/db", () => ({ queryAsMedio }));

const { listDrafts, countDrafts, PAGE_SIZE } = await import("@/lib/drafts");

beforeEach(() => {
  queryAsMedio.mockReset();
  queryAsMedio.mockResolvedValue([]);
});

const MEDIO = "11111111-1111-1111-1111-111111111111";

describe("listDrafts (normalización de filtros)", () => {
  it("sin filtros: estados=null, q=null, orden DESC, offset 0", async () => {
    await listDrafts(MEDIO);
    const call = queryAsMedio.mock.calls[0]!;
    const params = call[2] as unknown[];
    expect(params).toEqual([null, null, PAGE_SIZE, 0]);
  });

  it("page=3 → offset = 2 * PAGE_SIZE", async () => {
    await listDrafts(MEDIO, { page: 3 });
    const call = queryAsMedio.mock.calls[0]!;
    const params = call[2] as unknown[];
    expect(params[3]).toBe(2 * PAGE_SIZE);
  });

  it("page < 1 se normaliza a 1", async () => {
    await listDrafts(MEDIO, { page: 0 });
    const call = queryAsMedio.mock.calls[0]!;
    const params = call[2] as unknown[];
    expect(params[3]).toBe(0);
  });

  it("estados válidos se pasan como array, los inválidos se filtran", async () => {
    // @ts-expect-error — entrada inválida intencionada
    await listDrafts(MEDIO, { estados: ["borrador", "inexistente", "aprobado"] });
    const call = queryAsMedio.mock.calls[0]!;
    const params = call[2] as unknown[];
    expect(params[0]).toEqual(["borrador", "aprobado"]);
  });

  it("array de estados vacío se trata como null (todos)", async () => {
    await listDrafts(MEDIO, { estados: [] });
    const call = queryAsMedio.mock.calls[0]!;
    const params = call[2] as unknown[];
    expect(params[0]).toBeNull();
  });

  it("q se pasa trimmed; vacío → null", async () => {
    await listDrafts(MEDIO, { q: "  presupuestos  " });
    const first = queryAsMedio.mock.calls[0]![2] as unknown[];
    expect(first[1]).toBe("presupuestos");

    queryAsMedio.mockClear();
    await listDrafts(MEDIO, { q: "   " });
    const second = queryAsMedio.mock.calls[0]![2] as unknown[];
    expect(second[1]).toBeNull();
  });

  it("orden=titulo cambia el ORDER BY del SQL", async () => {
    await listDrafts(MEDIO, { orden: "titulo" });
    const sql = queryAsMedio.mock.calls[0]![1] as string;
    expect(sql).toMatch(/ORDER BY d\.titulo ASC/);
  });

  it("orden=antiguo cambia el ORDER BY a creado_at ASC", async () => {
    await listDrafts(MEDIO, { orden: "antiguo" });
    const sql = queryAsMedio.mock.calls[0]![1] as string;
    expect(sql).toMatch(/ORDER BY d\.creado_at ASC/);
  });

  it("orden default es creado_at DESC (reciente)", async () => {
    await listDrafts(MEDIO);
    const sql = queryAsMedio.mock.calls[0]![1] as string;
    expect(sql).toMatch(/ORDER BY d\.creado_at DESC/);
  });

  it("mapea filas BD a DraftRow con creadoAt como Date", async () => {
    queryAsMedio.mockResolvedValueOnce([
      {
        id: "abc",
        titulo: "T",
        estado: "borrador",
        creado_at: "2026-05-24T17:42:00Z",
        redactor_nombre: "Pepe",
        requiere_revision: true,
        n_errores: 3,
      },
    ]);
    const rows = await listDrafts(MEDIO);
    expect(rows).toHaveLength(1);
    expect(rows[0]!.creadoAt).toBeInstanceOf(Date);
    expect(rows[0]!.requiereRevision).toBe(true);
    expect(rows[0]!.nErrores).toBe(3);
  });

  it("nErrores como string se parsea a int", async () => {
    queryAsMedio.mockResolvedValueOnce([
      {
        id: "abc",
        titulo: "T",
        estado: "borrador",
        creado_at: new Date(),
        redactor_nombre: null,
        requiere_revision: false,
        n_errores: "7",
      },
    ]);
    const rows = await listDrafts(MEDIO);
    expect(rows[0]!.nErrores).toBe(7);
  });
});

describe("countDrafts", () => {
  it("devuelve 0 si la query no trae filas", async () => {
    queryAsMedio.mockResolvedValueOnce([]);
    const n = await countDrafts(MEDIO);
    expect(n).toBe(0);
  });

  it("devuelve el campo n", async () => {
    queryAsMedio.mockResolvedValueOnce([{ n: 42 }]);
    const n = await countDrafts(MEDIO);
    expect(n).toBe(42);
  });

  it("pasa los mismos filtros normalizados que listDrafts", async () => {
    await countDrafts(MEDIO, { q: "florece", estados: ["borrador"] });
    const call = queryAsMedio.mock.calls[0]!;
    const params = call[2] as unknown[];
    expect(params).toEqual([["borrador"], "florece"]);
  });
});
