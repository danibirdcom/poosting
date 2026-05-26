import { describe, it, expect } from "vitest";
import { NoOpPublisher } from "@/lib/cms/publisher";

describe("NoOpPublisher", () => {
  const draft = {
    id: "id",
    titulo: "t",
    meta_title: null,
    meta_descr: null,
    slug: null,
    cuerpo_md: "c",
    schema_jsonld: null,
    imagen_destacada_url: null,
    imagen_destacada_alt: null,
  };

  it("publishDraft devuelve error con mensaje claro", async () => {
    const res = await new NoOpPublisher().publishDraft(draft);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.error).toMatch(/PR3/);
      expect(res.error).toMatch(/Opennemas/);
    }
  });

  it("updatePost devuelve error", async () => {
    const res = await new NoOpPublisher().updatePost("123", draft);
    expect(res.ok).toBe(false);
  });
});
