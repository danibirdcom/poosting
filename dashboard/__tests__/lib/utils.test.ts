import { describe, it, expect } from "vitest";
import { cn } from "@/lib/utils";

describe("cn", () => {
  it("compone clases simples", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("descarta falsy", () => {
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
  });

  it("hace merge de utilidades conflictivas (tailwind-merge)", () => {
    // px-2 + px-4 → solo px-4 gana
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});
