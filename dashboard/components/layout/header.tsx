import { LogoutButton } from "@/components/auth/logout-button";

type Props = {
  userName: string;
  userEmail: string;
};

export function Header({ userName, userEmail }: Props) {
  const appName = process.env.NEXT_PUBLIC_APP_NAME ?? "Redactia";
  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-6">
      <div className="text-sm text-muted-foreground">{appName}</div>
      <div className="flex items-center gap-3">
        <div className="text-right">
          <p className="text-sm font-medium leading-tight">{userName}</p>
          <p className="text-xs leading-tight text-muted-foreground">{userEmail}</p>
        </div>
        <LogoutButton />
      </div>
    </header>
  );
}
