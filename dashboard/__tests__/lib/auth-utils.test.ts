import { describe, it, expect, vi, beforeEach } from "vitest";

const authMock = vi.fn();
vi.mock("@/auth", () => ({ auth: authMock }));

// Mock de redirect: en tests no podemos seguir un redirect real. Lo
// convertimos en una excepción reconocible.
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`__REDIRECT__:${url}`);
  },
}));

const { getSessionWithMedio, requireSession, requireMedioId } = await import(
  "@/lib/auth-utils"
);

beforeEach(() => {
  authMock.mockReset();
});

const SESSION = {
  user: {
    id: "u",
    email: "x@y.z",
    name: "X",
    medioId: "m",
    medioRol: "editor_jefe",
    rolGlobal: null,
  },
};

describe("getSessionWithMedio", () => {
  it("devuelve null si no hay sesión", async () => {
    authMock.mockResolvedValueOnce(null);
    expect(await getSessionWithMedio()).toBeNull();
  });

  it("devuelve null si la sesión no tiene medioId", async () => {
    authMock.mockResolvedValueOnce({ user: { id: "u" } });
    expect(await getSessionWithMedio()).toBeNull();
  });

  it("devuelve la sesión tal cual si está completa", async () => {
    authMock.mockResolvedValueOnce(SESSION);
    const s = await getSessionWithMedio();
    expect(s?.user.medioId).toBe("m");
  });
});

describe("requireSession / requireMedioId", () => {
  it("requireSession redirige a /login si null", async () => {
    authMock.mockResolvedValueOnce(null);
    await expect(requireSession()).rejects.toThrow("__REDIRECT__:/login");
  });

  it("requireMedioId devuelve el medioId cuando hay sesión", async () => {
    authMock.mockResolvedValueOnce(SESSION);
    expect(await requireMedioId()).toBe("m");
  });
});
