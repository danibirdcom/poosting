import { ExternalLink, Quote } from "lucide-react";
import type { FuenteRun } from "@/lib/draft-detail";

type Props = {
  fuentes: FuenteRun[];
};

const COMPETIDORES = [
  "elperiodicodearagon.com",
  "elespanol.com",
  "heraldo.es",
  "aragondigital.es",
  "20minutos.es",
  "elpais.com",
  "elmundo.es",
  "abc.es",
  "larazon.es",
  "cartv.es",
];

const AGENCIAS = ["efe.com", "europapress.es", "reuters.com", "apnews.com", "afp.com"];

const INSTITUCIONAL = [
  "boe.es",
  "boa.aragon.es",
  "zaragoza.es",
  "aragon.es",
  "lamoncloa.gob.es",
  "ine.es",
];

type Categoria = "competidor" | "agencia" | "institucional" | "otro";

function categorizar(url: string): Categoria {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (COMPETIDORES.some((d) => host === d || host.endsWith("." + d))) {
      return "competidor";
    }
    if (AGENCIAS.some((d) => host === d || host.endsWith("." + d))) {
      return "agencia";
    }
    if (INSTITUCIONAL.some((d) => host === d || host.endsWith("." + d))) {
      return "institucional";
    }
    return "otro";
  } catch {
    return "otro";
  }
}

const BADGE_CLASS: Record<Categoria, string> = {
  competidor: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  agencia: "bg-blue-500/10 text-blue-700 dark:text-blue-400",
  institucional: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  otro: "bg-muted text-muted-foreground",
};

const BADGE_LABEL: Record<Categoria, string> = {
  competidor: "competidor",
  agencia: "agencia",
  institucional: "institucional",
  otro: "otro",
};

export function FuentesList({ fuentes }: Props) {
  if (fuentes.length === 0) {
    return (
      <section className="rounded-lg border border-border bg-card p-3">
        <h2 className="mb-2 text-sm font-semibold">Fuentes</h2>
        <p className="text-xs text-muted-foreground">
          Sin fuentes registradas en este run.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <header className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Fuentes ({fuentes.length})</h2>
      </header>
      <ul className="space-y-2">
        {fuentes.map((f) => {
          const cat = categorizar(f.url);
          return (
            <li key={f.url} className="text-xs">
              <div className="flex items-start gap-2">
                <span
                  className={`mt-0.5 inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${BADGE_CLASS[cat]}`}
                >
                  {BADGE_LABEL[cat]}
                </span>
                <div className="min-w-0 flex-1">
                  <a
                    href={f.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="flex items-center gap-1 truncate font-medium text-foreground hover:underline"
                    title={f.url}
                  >
                    <span className="truncate">{f.titulo || f.url}</span>
                    <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />
                  </a>
                  <p className="truncate text-muted-foreground" title={f.url}>
                    {hostnameOf(f.url)}
                    {f.autoridadScore !== null
                      ? ` · autoridad ${f.autoridadScore.toFixed(2)}`
                      : ""}
                  </p>
                </div>
                {f.citadoEnArticulo ? (
                  <Quote
                    className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400"
                    aria-label="citada en el artículo"
                  />
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
