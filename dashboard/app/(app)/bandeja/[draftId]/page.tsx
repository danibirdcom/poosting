import Link from "next/link";
import { notFound } from "next/navigation";
import { requireMedioId } from "@/lib/auth-utils";
import { getDraftBundle } from "@/lib/draft-detail";
import { DraftEditor } from "@/components/editor/draft-editor";

export const dynamic = "force-dynamic";

type Params = { draftId: string };

export default async function DraftDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { draftId } = await params;
  const medioId = await requireMedioId();
  const bundle = await getDraftBundle(medioId, draftId);
  if (!bundle) {
    notFound();
  }

  return (
    <div className="space-y-4">
      <div>
        <Link
          href="/bandeja"
          className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          ← Volver a bandeja
        </Link>
      </div>
      <DraftEditor bundle={bundle} />
    </div>
  );
}
