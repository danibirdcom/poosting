import { FuentesList } from "@/components/editor/fuentes-list";
import { HechosList } from "@/components/editor/hechos-list";
import { ReviewBlock } from "@/components/editor/review-block";
import { ImagenDestacadaCard } from "@/components/editor/imagen-destacada";
import { JsonLdPreview } from "@/components/editor/jsonld-preview";
import type {
  ImagenDestacada,
  FuenteRun,
  ReviewOutput,
  ResearchOutput,
} from "@/lib/draft-detail";

type Props = {
  imagen: ImagenDestacada | null;
  review: ReviewOutput | null;
  research: ResearchOutput | null;
  fuentes: FuenteRun[];
  schemaJsonld: unknown | null;
};

/*
 * Panel lateral del editor (read-only). Reúne los bloques que ayudan
 * al humano a decidir si aprobar / rechazar: imagen destacada, errores
 * y sugerencias del review automático, fuentes citadas, hechos
 * sintetizados por research y el JSON-LD que se publicará.
 */
export function SidePanel({
  imagen,
  review,
  research,
  fuentes,
  schemaJsonld,
}: Props) {
  return (
    <aside className="space-y-4">
      <ImagenDestacadaCard imagen={imagen} />
      <ReviewBlock review={review} />
      <FuentesList fuentes={fuentes} />
      <HechosList research={research} />
      <JsonLdPreview schemaJsonld={schemaJsonld} />
    </aside>
  );
}
