import { AlertTriangle, Image as ImageIcon } from "lucide-react";
import type { ImagenDestacada } from "@/lib/draft-detail";

type Props = {
  imagen: ImagenDestacada | null;
};

const FUENTE_LABEL: Record<string, string> = {
  banco_licencia: "Banco con licencia",
  nano_banana_2: "IA · Nano Banana 2",
  gpt_image_2: "IA · GPT Image 2",
  manual: "Manual",
};

/*
 * Tarjeta de imagen destacada. Si el draft no tiene imagen asignada
 * muestra un placeholder + aviso. En PR2 no permitimos cambiar la URL
 * desde aquí (router de imagen sigue siendo responsabilidad del worker).
 * Si hace falta sustituirla, se hace desde el CMS tras publicar.
 */
export function ImagenDestacadaCard({ imagen }: Props) {
  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <header className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Imagen destacada</h2>
        {imagen ? (
          <span className="text-xs text-muted-foreground">
            {FUENTE_LABEL[imagen.fuente] ?? imagen.fuente}
          </span>
        ) : null}
      </header>
      {imagen ? (
        <div className="space-y-2">
          {imagen.urlPublica ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imagen.urlPublica}
              alt={imagen.altText}
              className="h-40 w-full rounded-md object-cover"
            />
          ) : (
            <div className="flex h-40 w-full items-center justify-center rounded-md border border-dashed border-border bg-muted/40 text-xs text-muted-foreground">
              <ImageIcon className="mr-2 h-4 w-4" />
              Sin URL pública
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            <strong className="font-medium">Alt:</strong> {imagen.altText || "—"}
          </p>
          <p className="text-xs text-muted-foreground">
            <strong className="font-medium">Pie:</strong> {imagen.pieFoto || "—"}
          </p>
          {!imagen.declaracionIaVisible &&
          (imagen.fuente === "nano_banana_2" || imagen.fuente === "gpt_image_2") ? (
            <p className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              Declaración IA no visible: revisa antes de publicar.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="flex h-32 items-center justify-center rounded-md border border-dashed border-border text-xs text-muted-foreground">
          Sin imagen asignada
        </div>
      )}
    </section>
  );
}
