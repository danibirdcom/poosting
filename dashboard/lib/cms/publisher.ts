/*
 * Interfaz CmsPublisher.
 *
 * PR2 deja la interfaz definida pero el único implementación es
 * `NoOpPublisher`, que arroja error. PR3 entra el `OpennemasPublisher`
 * para Hoy Aragón (pendiente respuesta de Openhost sobre la API REST).
 *
 * El flujo "Aprobar" en PR2 NO invoca al publisher: solo cambia
 * `drafts.estado = 'aprobado'` y registra en auditoria_humano. La
 * publicación real al CMS es una acción separada que se desbloquea
 * en PR3.
 */

export type PublishableDraft = {
  id: string;
  titulo: string;
  meta_title: string | null;
  meta_descr: string | null;
  slug: string | null;
  cuerpo_md: string;
  schema_jsonld: unknown;
  imagen_destacada_url: string | null;
  imagen_destacada_alt: string | null;
};

export type PublishResult =
  | { ok: true; externalId: string; externalUrl: string }
  | { ok: false; error: string };

export interface CmsPublisher {
  publishDraft(draft: PublishableDraft): Promise<PublishResult>;
  updatePost(externalId: string, draft: PublishableDraft): Promise<PublishResult>;
}

export class NoOpPublisher implements CmsPublisher {
  static readonly UNAVAILABLE =
    "CmsPublisher no implementado: la publicación al CMS llega en PR3 con el adapter de Opennemas.";

  async publishDraft(): Promise<PublishResult> {
    return { ok: false, error: NoOpPublisher.UNAVAILABLE };
  }
  async updatePost(): Promise<PublishResult> {
    return { ok: false, error: NoOpPublisher.UNAVAILABLE };
  }
}
