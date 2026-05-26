import type { ResearchOutput } from "@/lib/draft-detail";

type Props = {
  research: ResearchOutput | null;
};

/*
 * Lista de hechos sintetizados por el nodo research. Solo lectura.
 * Si no hay output (research abortó), mostramos placeholder.
 */
export function HechosList({ research }: Props) {
  const hechos = research?.hechosVerificados ?? [];
  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <h2 className="mb-2 text-sm font-semibold">
        Hechos sintetizados {hechos.length ? `(${hechos.length})` : ""}
      </h2>
      {hechos.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Sin hechos en el output de research.
        </p>
      ) : (
        <ol className="space-y-1 text-xs">
          {hechos.map((h, i) => (
            <li key={i} className="rounded-md border border-border bg-muted/30 px-2 py-1">
              <span className="text-muted-foreground">{i + 1}.</span>{" "}
              <span>{h}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
