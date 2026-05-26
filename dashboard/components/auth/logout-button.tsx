"use client";

import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { logoutAction } from "@/lib/auth-actions";

/*
 * Botón de logout. La server action `logoutAction` llama a signOut() y
 * redirige a /login. Lo envolvemos en un <form> para que funcione sin
 * JavaScript también.
 */
export function LogoutButton() {
  return (
    <form action={logoutAction}>
      <Button
        type="submit"
        variant="ghost"
        size="sm"
        className="gap-2 text-xs text-muted-foreground hover:text-foreground"
      >
        <LogOut className="h-3.5 w-3.5" />
        Salir
      </Button>
    </form>
  );
}
