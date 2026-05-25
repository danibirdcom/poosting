export function Header() {
  // PR1: header mínimo. En PR2 entra el toggle de tema + perfil de usuario.
  const appName = process.env.NEXT_PUBLIC_APP_NAME ?? "Redactia";
  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-6">
      <div className="text-sm text-muted-foreground">{appName}</div>
    </header>
  );
}
