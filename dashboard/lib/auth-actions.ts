"use server";

import { signOut } from "@/auth";

/*
 * Server Actions de auth distintas del login.
 *
 * Convertí esto en un módulo aparte porque el formulario de logout
 * (Client Component) debe importar solo actions, y el login vive en
 * `app/(auth)/login/actions.ts`.
 */

export async function logoutAction(): Promise<void> {
  await signOut({ redirectTo: "/login" });
}
