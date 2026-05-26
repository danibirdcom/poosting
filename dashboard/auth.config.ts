import type { NextAuthConfig } from "next-auth";

/*
 * Config edge-safe de NextAuth.
 *
 * Este objeto NO importa nada de Node-only (pg, argon2, fs, …) porque lo
 * carga el `middleware.ts`, que corre en runtime edge. Los providers y
 * callbacks que tocan BD viven en `auth.ts` (Node runtime).
 *
 * Aquí solo:
 *   - declaramos `pages.signIn` para que el redirect automático sepa
 *     dónde mandar al usuario sin sesión,
 *   - implementamos callbacks puros (jwt, session, authorized) que NO
 *     hacen I/O. La parte de BD (lookup de usuario + medio) entra en
 *     `auth.ts` vía Credentials.authorize.
 */

export const authConfig: NextAuthConfig = {
  providers: [], // se rellena en auth.ts (Node)
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt",
    maxAge: 12 * 60 * 60, // 12h
  },
  callbacks: {
    /**
     * Copia los campos de Redactia (medioId, medioRol, rolGlobal) del
     * `user` (en el primer login) al JWT que viaja en cookie. En llamadas
     * posteriores `user` es undefined y el token ya los lleva.
     */
    jwt({ token, user }) {
      if (user) {
        token.sub = user.id;
        token.medioId = user.medioId;
        token.medioRol = user.medioRol;
        token.rolGlobal = user.rolGlobal;
      }
      return token;
    },
    /**
     * Expone los campos custom del JWT en `session.user` para que los
     * Server Components puedan leerlos sin volver a tocar BD.
     */
    session({ session, token }) {
      if (token.sub) session.user.id = token.sub;
      session.user.medioId = token.medioId;
      session.user.medioRol = token.medioRol;
      session.user.rolGlobal = token.rolGlobal;
      return session;
    },
  },
  trustHost: true,
};
