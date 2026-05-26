import Link from "next/link";
import type { Route } from "next";
import { Inbox, Activity, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

type NavItem = {
  href: Route | string;
  label: string;
  icon: typeof Inbox;
  enabled: boolean;
};

// Trazabilidad y Configuración son placeholder (entran en PR4 / PR2).
// Sus hrefs no son rutas existentes todavía → usamos `string` allí; el Link
// se renderiza como <span> deshabilitado.
const items: NavItem[] = [
  { href: "/bandeja" as Route, label: "Bandeja", icon: Inbox, enabled: true },
  { href: "/trazabilidad", label: "Trazabilidad", icon: Activity, enabled: false },
  { href: "/ajustes", label: "Ajustes", icon: Settings, enabled: false },
];

export function Sidebar() {
  return (
    <aside className="hidden w-56 shrink-0 border-r border-border bg-muted/30 md:block">
      <div className="flex h-14 items-center border-b border-border px-4">
        <Link href="/" className="text-sm font-semibold tracking-tight">
          Redactia
        </Link>
      </div>
      <nav className="space-y-1 p-2">
        {items.map((item) => {
          const Icon = item.icon;
          const className = cn(
            "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
            item.enabled
              ? "text-foreground hover:bg-accent hover:text-accent-foreground"
              : "cursor-not-allowed text-muted-foreground opacity-60"
          );
          if (!item.enabled) {
            return (
              <span key={item.href} className={className} aria-disabled>
                <Icon className="h-4 w-4" />
                {item.label}
                <span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground">
                  pronto
                </span>
              </span>
            );
          }
          return (
            <Link key={item.href} href={item.href as Route} className={className}>
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
