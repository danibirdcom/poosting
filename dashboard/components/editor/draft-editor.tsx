import { EstadoBadge } from "@/components/bandeja/estado-badge";
import { EditorForm } from "@/components/editor/editor-form";
import { SidePanel } from "@/components/editor/side-panel";
import { FooterAcciones } from "@/components/editor/footer-acciones";
import type { DraftBundle } from "@/lib/draft-detail";

/*
 * Pantalla del editor. Server Component: pasa el bundle (lectura BD)
 * a los Client Components que manejan estado e interacción.
 *
 * Layout 2 columnas (md+): 60% / 40%. En pantallas pequeñas las dos
 * columnas se apilan.
 *
 * El estado editable (titulo, meta_title, meta_descr, slug, cuerpo_md)
 * vive en `EditorForm` (client). Los datos read-only (fuentes, hechos,
 * imagen, errores de review) se renderizan en `SidePanel` (server).
 */

type Props = {
  bundle: DraftBundle;
};

export function DraftEditor({ bundle }: Props) {
  const { draft, review, research, fuentes } = bundle;

  return (
    <div className="space-y-4 pb-24">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">
            Draft · {draft.redactor?.nombre ?? "sin redactor"}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">
            {draft.titulo}
          </h1>
        </div>
        <EstadoBadge estado={draft.estado} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[3fr_2fr]">
        <div className="space-y-4">
          <EditorForm draft={draft} />
        </div>
        <SidePanel
          imagen={draft.imagenDestacada}
          review={review}
          research={research}
          fuentes={fuentes}
          schemaJsonld={draft.schemaJsonld}
        />
      </div>

      <FooterAcciones
        draftId={draft.id}
        estado={draft.estado}
        motivoRechazo={draft.motivoRechazo}
      />
    </div>
  );
}
