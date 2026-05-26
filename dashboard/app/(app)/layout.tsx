import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";

/*
 * Layout autenticado: sidebar + header + main. El middleware ya protege
 * las rutas bajo PROTECTED_PREFIXES, pero hacemos un guard extra aquí
 * para defensa en profundidad y para extraer la sesión que el header usa.
 */
export default async function AppLayout({ children }: { children: ReactNode }) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <Header
          userName={session.user.name}
          userEmail={session.user.email}
        />
        <main className="flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
