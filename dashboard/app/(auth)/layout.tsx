import type { ReactNode } from "react";

/*
 * Layout para rutas no autenticadas (login). Sin sidebar ni header — la
 * página de login es pantalla completa.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
