import { describe, it, expect, vi, beforeEach } from "vitest";

const queryAsMedio = vi.fn();
vi.mock("@/lib/db", () => ({ queryAsMedio }));

const { saveDraft, approveDraft, rejectDraft, archiveDraft, SaveDraftSchema, RejectDraftSchema } =
  await import("@/lib/drafts-update");

const CTX = {
  draftId: "33333333-3333-3333-3333-333333333333",
  medioId: "11111111-1111-1111-1111-111111111111",
  usuarioId: "22222222-2222-2222-2222-222222222222",
};

const VALID_INPUT = {
  titulo: "Un título suficientemente largo",
  meta_title: "Meta title de unos 50 chars para ranking SEO bueno",
  meta_descr:
    "Esta es una meta description con más de 80 caracteres porque el SEO premia descripciones detalladas que cubran el tema sin pasarse de los 160.",
  slug: "slug-valido-con-guiones",
  cuerpo_md:
    "Lorem ipsum dolor sit amet consectetur adipiscing elit. ".repeat(20),
};

beforeEach(() => {
  queryAsMedio.mockReset();
});

describe("SaveDraftSchema", () => {
  it("acepta input válido", () => {
    expect(SaveDraftSchema.safeParse(VALID_INPUT).success).toBe(true);
  });

  it("rechaza slug con mayúsculas o espacios", () => {
    expect(
      SaveDraftSchema.safeParse({ ...VALID_INPUT, slug: "Slug Invalido" }).success
    ).toBe(false);
  });

  it("rechaza meta_title de 19 chars", () => {
    expect(
      SaveDraftSchema.safeParse({ ...VALID_INPUT, meta_title: "x".repeat(19) }).success
    ).toBe(false);
  });

  it("acepta meta_title nullable", () => {
    expect(
      SaveDraftSchema.safeParse({ ...VALID_INPUT, meta_title: null }).success
    ).toBe(true);
  });
});

describe("saveDraft", () => {
  function mockSnapshot(snap: Record<string, string | null>) {
    queryAsMedio.mockResolvedValueOnce([snap]); // SELECT snapshot
  }

  it("no UPDATE ni audit si no hay cambios", async () => {
    mockSnapshot({
      titulo: VALID_INPUT.titulo,
      meta_title: VALID_INPUT.meta_title,
      meta_descr: VALID_INPUT.meta_descr,
      slug: VALID_INPUT.slug,
      cuerpo_md: VALID_INPUT.cuerpo_md,
    });
    const res = await saveDraft(CTX, VALID_INPUT);
    expect(res).toEqual({ ok: true, diff: {}, changed: false });
    // Solo la SELECT inicial, sin UPDATE ni INSERT.
    expect(queryAsMedio).toHaveBeenCalledTimes(1);
  });

  it("UPDATE drafts + INSERT auditoria_humano cuando cambia el título", async () => {
    mockSnapshot({
      titulo: "Anterior",
      meta_title: VALID_INPUT.meta_title,
      meta_descr: VALID_INPUT.meta_descr,
      slug: VALID_INPUT.slug,
      cuerpo_md: VALID_INPUT.cuerpo_md,
    });
    queryAsMedio.mockResolvedValueOnce([]); // UPDATE drafts
    queryAsMedio.mockResolvedValueOnce([]); // INSERT auditoria
    const res = await saveDraft(CTX, VALID_INPUT);

    expect(res.ok).toBe(true);
    expect(queryAsMedio).toHaveBeenCalledTimes(3);
    const updateCall = queryAsMedio.mock.calls[1]!;
    expect(updateCall[1]).toMatch(/UPDATE drafts/);
    expect(updateCall[2]).toEqual([
      VALID_INPUT.titulo,
      VALID_INPUT.meta_title,
      VALID_INPUT.meta_descr,
      VALID_INPUT.slug,
      VALID_INPUT.cuerpo_md,
      CTX.draftId,
    ]);
    const auditCall = queryAsMedio.mock.calls[2]!;
    expect(auditCall[1]).toMatch(/INSERT INTO auditoria_humano/);
    expect(auditCall[2]![3]).toBe("editado");
  });

  it("error si el draft no existe (snapshot vacío)", async () => {
    queryAsMedio.mockResolvedValueOnce([]); // SELECT snapshot empty
    const res = await saveDraft(CTX, VALID_INPUT);
    expect(res).toEqual({ ok: false, error: "Draft no encontrado" });
  });
});

describe("approveDraft", () => {
  it("UPDATE estado=aprobado WHERE estado=borrador + audit", async () => {
    queryAsMedio.mockResolvedValueOnce([{ estado: "aprobado" }]); // UPDATE returning
    queryAsMedio.mockResolvedValueOnce([]); // INSERT audit
    const res = await approveDraft(CTX);
    expect(res).toEqual({ ok: true });
    const updateCall = queryAsMedio.mock.calls[0]!;
    expect(updateCall[1]).toMatch(/UPDATE drafts SET estado = 'aprobado'/);
    expect(updateCall[1]).toMatch(/estado = 'borrador'/);
  });

  it("error si el draft no estaba en borrador (UPDATE no devolvió filas)", async () => {
    queryAsMedio.mockResolvedValueOnce([]); // UPDATE returning nada
    const res = await approveDraft(CTX);
    expect(res.ok).toBe(false);
    expect(queryAsMedio).toHaveBeenCalledTimes(1); // no audit
  });
});

describe("rejectDraft", () => {
  it("guarda motivo_rechazo + audit con notas", async () => {
    queryAsMedio.mockResolvedValueOnce([{ estado: "rechazado" }]);
    queryAsMedio.mockResolvedValueOnce([]);
    const res = await rejectDraft(CTX, { motivo: "Fuente no fiable" });
    expect(res.ok).toBe(true);
    const updateCall = queryAsMedio.mock.calls[0]!;
    expect(updateCall[1]).toMatch(/motivo_rechazo = \$2/);
    expect(updateCall[2]).toEqual([CTX.draftId, "Fuente no fiable"]);
    const auditCall = queryAsMedio.mock.calls[1]!;
    expect(auditCall[2]![3]).toBe("rechazado");
    expect(auditCall[2]![4]).toBe("Fuente no fiable");
  });

  it("RejectDraftSchema rechaza motivos cortos", () => {
    expect(RejectDraftSchema.safeParse({ motivo: "corto" }).success).toBe(false);
    expect(RejectDraftSchema.safeParse({ motivo: "x".repeat(10) }).success).toBe(true);
  });
});

describe("archiveDraft", () => {
  it("UPDATE estado=archivado + audit", async () => {
    queryAsMedio.mockResolvedValueOnce([{ estado: "archivado" }]);
    queryAsMedio.mockResolvedValueOnce([]);
    const res = await archiveDraft(CTX);
    expect(res.ok).toBe(true);
    const updateCall = queryAsMedio.mock.calls[0]!;
    expect(updateCall[1]).toMatch(/UPDATE drafts SET estado = 'archivado'/);
    // No archiva un publicado.
    expect(updateCall[1]).toMatch(/estado <> 'publicado'/);
  });

  it("error si el draft estaba publicado", async () => {
    queryAsMedio.mockResolvedValueOnce([]);
    const res = await archiveDraft(CTX);
    expect(res.ok).toBe(false);
  });
});
