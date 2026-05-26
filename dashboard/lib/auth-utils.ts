import { redirect } from "next/navigation";
import { auth } from "@/auth";
import type { Session } from "next-auth";

/*
 * Helpers para acceder a la sesión en Server Components.
 *
 * `getSessionWithMedio` no lanza: devuelve null si no hay sesión o si no
 * tiene medio asignado (caso raro: usuario sin usuarios_medios).
 *
 * `requireMedioId` lanza redirect → /login para los Server Components
 * que asumen sesión y prefieren no manejar el caso null.
 */

export type SessionWithMedio = Session & {
  user: {
    id: string;
    email: string;
    name: string;
    medioId: string;
    medioRol: "editor_jefe" | "redactor" | "colaborador";
    rolGlobal: "superadmin" | null;
  };
};

export async function getSessionWithMedio(): Promise<SessionWithMedio | null> {
  const session = await auth();
  if (!session?.user?.medioId) return null;
  return session as SessionWithMedio;
}

export async function requireSession(): Promise<SessionWithMedio> {
  const session = await getSessionWithMedio();
  if (!session) {
    redirect("/login");
  }
  return session;
}

export async function requireMedioId(): Promise<string> {
  const session = await requireSession();
  return session.user.medioId;
}
