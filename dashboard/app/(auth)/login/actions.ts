"use server";

import { AuthError } from "next-auth";
import { z } from "zod";
import { signIn } from "@/auth";

/*
 * Server Action de login.
 *
 * Cuando signIn() acepta credenciales, NextAuth lanza un redirect interno
 * (NEXT_REDIRECT) que el cliente sigue. Solo recibimos LoginState aquí en
 * caso de error de credenciales o validación de form.
 */

export type LoginState =
  | { ok: true }
  | { ok: false; error: string };

const LoginSchema = z.object({
  email: z.string().email("Email inválido").max(256),
  password: z.string().min(1, "Contraseña requerida").max(256),
  next: z.string().optional(),
});

export async function loginAction(
  _prev: LoginState | undefined,
  formData: FormData
): Promise<LoginState> {
  const parsed = LoginSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
    next: formData.get("next") || undefined,
  });
  if (!parsed.success) {
    const first = parsed.error.issues[0]?.message ?? "Formulario inválido";
    return { ok: false, error: first };
  }

  const next = sanitizeNext(parsed.data.next);

  try {
    await signIn("credentials", {
      email: parsed.data.email,
      password: parsed.data.password,
      redirectTo: next,
    });
    return { ok: true };
  } catch (err) {
    if (err instanceof AuthError) {
      if (err.type === "CredentialsSignin") {
        return { ok: false, error: "Email o contraseña incorrectos." };
      }
      return { ok: false, error: "No se pudo iniciar sesión." };
    }
    // Re-lanzar NEXT_REDIRECT y similares: el redirect interno de Next
    // no es un error real.
    throw err;
  }
}

/**
 * Solo acepta rutas internas absolutas (`/foo`) para evitar open redirect.
 * Rechaza `//host` (protocol-relative) y URLs absolutas.
 *
 * No exportada: en un "use server" file solo pueden vivir async functions
 * exportadas. Está testeada indirectamente vía loginAction.
 */
function sanitizeNext(raw: string | undefined): string {
  if (!raw) return "/bandeja";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/bandeja";
  return raw;
}
