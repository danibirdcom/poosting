import Link from "next/link";

type Params = { draftId: string };

// Placeholder: el editor de draft + aprobar/rechazar entra en PR2.
export default async function DraftDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { draftId } = await params;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Editor de draft</h1>
      <p className="text-sm text-muted-foreground">Draft ID: {draftId}</p>
      <p className="text-sm">
        Esta pantalla se implementa en PR2 (editor de draft + aprobar/rechazar).
      </p>
      <Link
        href="/bandeja"
        className="inline-block text-sm underline underline-offset-4"
      >
        ← Volver a bandeja
      </Link>
    </div>
  );
}
