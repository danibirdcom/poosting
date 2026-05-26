import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "Entrar — Redactia",
};

export const dynamic = "force-dynamic";

type SearchParams = { next?: string };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { next } = await searchParams;
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Redactia</h1>
          <p className="text-sm text-muted-foreground">
            Inicia sesión para acceder a la bandeja editorial
          </p>
        </div>
        <LoginForm next={next} />
      </div>
    </div>
  );
}
