import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import argon2 from "argon2";
import { z } from "zod";
import { authConfig } from "@/auth.config";
import { getRawPool } from "@/lib/db";

/*
 * Punto de entrada NextAuth (Node runtime).
 *
 * Define el Credentials provider que valida email+password contra la
 * tabla `usuarios` (password_hash argon2id) y carga el primer medio
 * asignado al usuario en `usuarios_medios`.
 *
 * usuarios y usuarios_medios NO tienen RLS (son globales / fuente de
 * verdad de membresía), por lo que aquí usamos `getRawPool()` y NO
 * `queryAsMedio()`: durante el login todavía no hay medio en sesión.
 */

const CredsSchema = z.object({
  email: z.string().email().toLowerCase().trim(),
  password: z.string().min(1).max(256),
});

type UsuarioRow = {
  id: string;
  email: string;
  nombre: string;
  password_hash: string;
  rol_global: "superadmin" | null;
};

type MembershipRow = {
  medio_id: string;
  rol: "editor_jefe" | "redactor" | "colaborador";
};

export const { handlers, auth, signIn, signOut } = NextAuth({
  ...authConfig,
  providers: [
    Credentials({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(rawCredentials) {
        const parsed = CredsSchema.safeParse(rawCredentials);
        if (!parsed.success) return null;
        const { email, password } = parsed.data;

        const pool = getRawPool();
        const client = await pool.connect();
        try {
          // 1) Lookup del usuario por email. Sin RLS, sin app.medio_actual.
          const userRes = await client.query<UsuarioRow>(
            `SELECT id::text, email, nombre, password_hash, rol_global
             FROM usuarios
             WHERE email = $1`,
            [email]
          );
          const user = userRes.rows[0];
          if (!user) return null;

          // 2) Verificar password. argon2.verify usa el hash íntegro
          //    (incluye sal y parámetros), por lo que no necesitamos
          //    pasarlos por separado.
          let valid = false;
          try {
            valid = await argon2.verify(user.password_hash, password);
          } catch {
            // hash corrupto / formato inválido → tratamos como no válido.
            valid = false;
          }
          if (!valid) return null;

          // 3) Cargar el primer medio asignado. Si el usuario no tiene
          //    ningún medio → no puede entrar (no hay UI sin tenant).
          const memberRes = await client.query<MembershipRow>(
            `SELECT medio_id::text, rol
             FROM usuarios_medios
             WHERE usuario_id = $1
             ORDER BY medio_id
             LIMIT 1`,
            [user.id]
          );
          const member = memberRes.rows[0];
          if (!member) return null;

          return {
            id: user.id,
            email: user.email,
            name: user.nombre,
            medioId: member.medio_id,
            medioRol: member.rol,
            rolGlobal: user.rol_global,
          };
        } finally {
          client.release();
        }
      },
    }),
  ],
});
