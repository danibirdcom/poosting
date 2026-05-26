import { queryAsMedio } from "@/lib/db";
import type { EstadoDraft } from "@/lib/drafts-types";

/*
 * Lectura del draft completo + datos relacionados para la pantalla
 * de editor. Multi-tenancy: RLS via queryAsMedio.
 *
 * Se hacen consultas independientes (en paralelo) en vez de un solo
 * SELECT mega con JOINs para que cada bloque sea tipable de forma
 * limpia. El coste es 3-4 round trips a la BD; aceptable para una
 * pantalla de edición.
 */

export type DraftDetail = {
  id: string;
  runId: string;
  titulo: string;
  metaTitle: string | null;
  metaDescr: string | null;
  slug: string | null;
  cuerpoMd: string;
  schemaJsonld: unknown | null;
  estado: EstadoDraft;
  motivoRechazo: string | null;
  creadoAt: Date;
  imagenDestacada: ImagenDestacada | null;
  redactor: { id: string; nombre: string } | null;
};

export type ImagenDestacada = {
  id: string;
  urlPublica: string | null;
  altText: string;
  pieFoto: string;
  fuente: string;
  declaracionIaVisible: boolean;
};

export type FuenteRun = {
  url: string;
  titulo: string | null;
  autoridadScore: number | null;
  citadoEnArticulo: boolean;
};

export type ReviewOutput = {
  aprobado: boolean | null;
  errores: string[];
  sugerencias: string[];
  requiereRevisionHumana: boolean;
};

export type ResearchOutput = {
  hechosVerificados: string[];
};

export type DraftBundle = {
  draft: DraftDetail;
  fuentes: FuenteRun[];
  review: ReviewOutput | null;
  research: ResearchOutput | null;
};

type DraftDbRow = {
  id: string;
  run_id: string;
  titulo: string;
  meta_title: string | null;
  meta_descr: string | null;
  slug: string | null;
  cuerpo_md: string;
  schema_jsonld: unknown | null;
  estado: EstadoDraft;
  motivo_rechazo: string | null;
  creado_at: Date | string;
  // imagen joined
  img_id: string | null;
  img_url_publica: string | null;
  img_alt_text: string | null;
  img_pie_foto: string | null;
  img_fuente: string | null;
  img_declaracion: boolean | null;
  // redactor joined
  redactor_id: string | null;
  redactor_nombre: string | null;
};

function asDate(v: Date | string): Date {
  return v instanceof Date ? v : new Date(v);
}

export async function getDraftBundle(
  medioId: string,
  draftId: string
): Promise<DraftBundle | null> {
  const draftRows = await queryAsMedio<DraftDbRow>(
    medioId,
    `SELECT
       d.id::text                   AS id,
       d.run_id::text               AS run_id,
       d.titulo                     AS titulo,
       d.meta_title                 AS meta_title,
       d.meta_descr                 AS meta_descr,
       d.slug                       AS slug,
       d.cuerpo_md                  AS cuerpo_md,
       d.schema_jsonld              AS schema_jsonld,
       d.estado                     AS estado,
       d.motivo_rechazo             AS motivo_rechazo,
       d.creado_at                  AS creado_at,
       img.id::text                 AS img_id,
       img.url_publica              AS img_url_publica,
       img.alt_text                 AS img_alt_text,
       img.pie_foto                 AS img_pie_foto,
       img.fuente                   AS img_fuente,
       img.declaracion_ia_visible   AS img_declaracion,
       r.id::text                   AS redactor_id,
       r.nombre_publico             AS redactor_nombre
     FROM drafts d
     LEFT JOIN imagenes_articulo img ON img.id = d.imagen_destacada_id
     LEFT JOIN runs ru               ON ru.id = d.run_id
     LEFT JOIN redactores r          ON r.id = ru.redactor_id
     WHERE d.id = $1`,
    [draftId]
  );
  const row = draftRows[0];
  if (!row) return null;

  const [fuentes, review, research] = await Promise.all([
    getFuentes(medioId, row.run_id),
    getReviewOutput(medioId, row.run_id),
    getResearchOutput(medioId, row.run_id),
  ]);

  const imagen: ImagenDestacada | null = row.img_id
    ? {
        id: row.img_id,
        urlPublica: row.img_url_publica,
        altText: row.img_alt_text ?? "",
        pieFoto: row.img_pie_foto ?? "",
        fuente: row.img_fuente ?? "manual",
        declaracionIaVisible: Boolean(row.img_declaracion),
      }
    : null;

  return {
    draft: {
      id: row.id,
      runId: row.run_id,
      titulo: row.titulo,
      metaTitle: row.meta_title,
      metaDescr: row.meta_descr,
      slug: row.slug,
      cuerpoMd: row.cuerpo_md,
      schemaJsonld: row.schema_jsonld,
      estado: row.estado,
      motivoRechazo: row.motivo_rechazo,
      creadoAt: asDate(row.creado_at),
      imagenDestacada: imagen,
      redactor:
        row.redactor_id && row.redactor_nombre
          ? { id: row.redactor_id, nombre: row.redactor_nombre }
          : null,
    },
    fuentes,
    review,
    research,
  };
}

async function getFuentes(medioId: string, runId: string): Promise<FuenteRun[]> {
  const rows = await queryAsMedio<{
    url: string;
    titulo: string | null;
    autoridad_score: number | string | null;
    citado_en_articulo: boolean;
  }>(
    medioId,
    `SELECT url, titulo, autoridad_score, citado_en_articulo
     FROM fuentes_run
     WHERE run_id = $1
     ORDER BY autoridad_score DESC NULLS LAST, url ASC`,
    [runId]
  );
  return rows.map((r) => ({
    url: r.url,
    titulo: r.titulo,
    autoridadScore:
      r.autoridad_score === null
        ? null
        : typeof r.autoridad_score === "string"
        ? parseFloat(r.autoridad_score)
        : r.autoridad_score,
    citadoEnArticulo: r.citado_en_articulo,
  }));
}

async function getReviewOutput(
  medioId: string,
  runId: string
): Promise<ReviewOutput | null> {
  const rows = await queryAsMedio<{ output: Record<string, unknown> | null }>(
    medioId,
    `SELECT output
     FROM run_steps
     WHERE run_id = $1
       AND step_nombre = 'review'
       AND estado = 'completado'
     ORDER BY finalizado_at DESC NULLS LAST
     LIMIT 1`,
    [runId]
  );
  const out = rows[0]?.output;
  if (!out || typeof out !== "object") return null;
  const errores = Array.isArray(out.errores) ? (out.errores as unknown[]) : [];
  const sugerencias = Array.isArray(out.sugerencias)
    ? (out.sugerencias as unknown[])
    : [];
  return {
    aprobado: typeof out.aprobado === "boolean" ? out.aprobado : null,
    errores: errores.filter((e): e is string => typeof e === "string"),
    sugerencias: sugerencias.filter((s): s is string => typeof s === "string"),
    requiereRevisionHumana: Boolean(out.requiere_revision_humana),
  };
}

async function getResearchOutput(
  medioId: string,
  runId: string
): Promise<ResearchOutput | null> {
  const rows = await queryAsMedio<{ output: Record<string, unknown> | null }>(
    medioId,
    `SELECT output
     FROM run_steps
     WHERE run_id = $1
       AND step_nombre = 'research'
       AND estado = 'completado'
     ORDER BY finalizado_at DESC NULLS LAST
     LIMIT 1`,
    [runId]
  );
  const out = rows[0]?.output;
  if (!out || typeof out !== "object") return null;
  const hechos = Array.isArray(out.hechos_verificados)
    ? (out.hechos_verificados as unknown[])
    : [];
  return {
    hechosVerificados: hechos.filter((h): h is string => typeof h === "string"),
  };
}
