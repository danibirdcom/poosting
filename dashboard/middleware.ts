import NextAuth from "next-auth";
import { NextResponse } from "next/server";
import { authConfig } from "@/auth.config";

/*
 * Middleware de protección de rutas. Corre en edge runtime, por eso
 * usa `authConfig` (sin pg/argon2) en lugar de `@/auth`.
 *
 * Reglas:
 *   - rutas en PROTECTED requieren sesión → redirect a /login?next=...
 *   - /login con sesión activa → redirect a /bandeja
 *   - / con sesión activa → /bandeja, sin sesión → /login
 *   - /api/auth/*, /api/health, /_next/*, /favicon.ico → siempre libres
 */

const { auth: authMiddleware } = NextAuth(authConfig);

const PROTECTED_PREFIXES = ["/bandeja", "/runs", "/admin"];
const PUBLIC_API = ["/api/auth", "/api/health"];

export default authMiddleware((req) => {
  const { pathname } = req.nextUrl;
  const isAuth = Boolean(req.auth);

  // Rutas siempre públicas (assets, health, NextAuth endpoints).
  if (
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico" ||
    PUBLIC_API.some((p) => pathname.startsWith(p))
  ) {
    return NextResponse.next();
  }

  const isProtected = PROTECTED_PREFIXES.some((p) => pathname.startsWith(p));

  if (isProtected && !isAuth) {
    const loginUrl = new URL("/login", req.url);
    // `next` permite volver a la URL original tras el login.
    loginUrl.searchParams.set("next", pathname + req.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  if (pathname === "/login" && isAuth) {
    return NextResponse.redirect(new URL("/bandeja", req.url));
  }

  if (pathname === "/") {
    return NextResponse.redirect(
      new URL(isAuth ? "/bandeja" : "/login", req.url)
    );
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
