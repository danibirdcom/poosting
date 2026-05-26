/*
 * Augmentación del tipo Session de NextAuth.
 *
 * El JWT y la session de Redactia llevan campos extra (medioId, medioRol,
 * rolGlobal) que poblamos en los callbacks de `auth.config.ts`. Sin esta
 * augmentación, el resto del código vería `session.user.medioId` como
 * any o error de TS strict.
 */

import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface User {
    id: string;
    email: string;
    name: string;
    medioId: string;
    medioRol: "editor_jefe" | "redactor" | "colaborador";
    rolGlobal: "superadmin" | null;
  }

  interface Session {
    user: {
      id: string;
      email: string;
      name: string;
      medioId: string;
      medioRol: "editor_jefe" | "redactor" | "colaborador";
      rolGlobal: "superadmin" | null;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    medioId: string;
    medioRol: "editor_jefe" | "redactor" | "colaborador";
    rolGlobal: "superadmin" | null;
  }
}
