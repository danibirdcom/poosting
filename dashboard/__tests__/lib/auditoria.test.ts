import { describe, it, expect, vi, beforeEach } from "vitest";

const queryAsMedio = vi.fn();
vi.mock("@/lib/db", () => ({ queryAsMedio }));

const { registerAuditEvent, diffDraftSnapshots } = await import("@/lib/auditoria");

beforeEach(() => {
  queryAsMedio.mockReset();
  queryAsMedio.mockResolvedValue([]);
});

const MEDIO = "11111111-1111-1111-1111-111111111111";
const USER = "22222222-2222-2222-2222-222222222222";
const DRAFT = "33333333-3333-3333-3333-333333333333";

describe("registerAuditEvent", () => {
  it("inserta en auditoria_humano con shape correcto", async () => {
    await registerAuditEvent({
      draftId: DRAFT,
      medioId: MEDIO,
      usuarioId: USER,
      accion: "aprobado",
    });
    expect(queryAsMedio).toHaveBeenCalledTimes(1);
    const [medioId, sql, params] = queryAsMedio.mock.calls[0]!;
    expect(medioId).toBe(MEDIO);
    expect(sql).toMatch(/INSERT INTO auditoria_humano/);
    expect(params).toEqual([DRAFT, MEDIO, USER, "aprobado", null, null]);
  });

  it("serializa diff_resumen a JSON cuando viene", async () => {
    await registerAuditEvent({
      draftId: DRAFT,
      medioId: MEDIO,
      usuarioId: USER,
      accion: "editado",
      diffResumen: { titulo: { before: "A", after: "B" } },
    });
    const params = queryAsMedio.mock.calls[0]![2] as unknown[];
    expect(params[5]).toBe('{"titulo":{"before":"A","after":"B"}}');
  });

  it("pasa notas tal cual cuando vienen", async () => {
    await registerAuditEvent({
      draftId: DRAFT,
      medioId: MEDIO,
      usuarioId: USER,
      accion: "rechazado",
      notas: "fuente sin verificar",
    });
    const params = queryAsMedio.mock.calls[0]![2] as unknown[];
    expect(params[4]).toBe("fuente sin verificar");
  });
});

describe("diffDraftSnapshots", () => {
  it("devuelve solo los campos que cambian", () => {
    const before = { titulo: "A", slug: "a-slug", meta_title: "x" };
    const after = { titulo: "A", slug: "b-slug", meta_title: "y" };
    expect(diffDraftSnapshots(before, after)).toEqual({
      slug: { before: "a-slug", after: "b-slug" },
      meta_title: { before: "x", after: "y" },
    });
  });

  it("trata null y string vacío como distintos", () => {
    const out = diffDraftSnapshots({ meta_title: null }, { meta_title: "" });
    expect(out).toEqual({ meta_title: { before: null, after: "" } });
  });

  it("objeto vacío si nada cambia", () => {
    expect(
      diffDraftSnapshots({ a: "x" }, { a: "x" })
    ).toEqual({});
  });
});
