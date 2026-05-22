"""Detector RSS.

Lee feeds configurados en ``ctx.config['feeds']``, parsea cada item y
produce una ``SenalCruda`` por entrada reciente. La "velocidad" se
aproxima como ``items_recientes_del_feed / minutos_ventana``.

Tolerante a feeds rotos: si uno falla, se loguea y se continúa con los demás.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx
import structlog

from .base import DetectorContext, SenalCruda

logger = structlog.get_logger(__name__)

VENTANA_HORAS = 6                 # consideramos items publicados en las últimas 6h
TIMEOUT_S = 15.0
USER_AGENT = "Redactia/0.1 (+https://redactia.es)"


class RSSDetector:
    nombre = "rss"

    async def detectar(self, ctx: DetectorContext) -> list[SenalCruda]:
        feeds: list[str] = ctx.config.get("feeds", []) or []
        if not feeds:
            return []

        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            tasks = [self._procesar_feed(client, ctx, url) for url in feeds]
            resultados = await asyncio.gather(*tasks, return_exceptions=True)

        senales: list[SenalCruda] = []
        for url, res in zip(feeds, resultados, strict=True):
            if isinstance(res, BaseException):
                logger.warning("rss_feed_error", url=url, error=str(res))
                continue
            senales.extend(res)
        return senales

    async def _procesar_feed(
        self, client: httpx.AsyncClient, ctx: DetectorContext, feed_url: str
    ) -> list[SenalCruda]:
        resp = await client.get(feed_url)
        resp.raise_for_status()
        items = parse_feed_items(resp.text)

        ahora = datetime.now(tz=UTC)
        ventana_inicio = ahora - timedelta(hours=VENTANA_HORAS)
        items_recientes = [it for it in items if it["fecha"] >= ventana_inicio]

        if not items_recientes:
            return []

        minutos_ventana = max(1.0, VENTANA_HORAS * 60.0)
        velocidad = len(items_recientes) / minutos_ventana
        dominio_paywall = (
            ctx.usar_solo_como_senal or _es_dominio_paywall(feed_url)
        )

        senales: list[SenalCruda] = []
        for it in items_recientes:
            if not _pasa_keywords(it["titulo"], ctx):
                continue
            senales.append(
                SenalCruda(
                    origen="rss",
                    termino=it["titulo"],
                    categoria=ctx.categoria_destino,
                    pais=ctx.pais,
                    region=None,
                    velocidad=velocidad,
                    volumen=1,
                    url_origen=it.get("link"),
                    paywall=dominio_paywall,
                    expira_en_horas=24,
                    metadatos={
                        "feed_url": feed_url,
                        "fecha_publicacion": it["fecha"].isoformat(),
                        "resumen": it.get("resumen", "")[:500],
                    },
                )
            )
        return senales


def parse_feed_items(xml_text: str) -> list[dict[str, Any]]:
    """Parsea un XML RSS 2.0 o Atom y devuelve items {titulo, link, fecha, resumen}.

    Implementación minimalista para no depender de feedparser. Maneja:
    - RSS 2.0: ``//item`` con ``title``, ``link``, ``pubDate``, ``description``.
    - Atom 1.0: ``//entry`` con ``title``, ``link[@rel='alternate']``, ``updated``, ``summary``.

    Devuelve fechas con tz=UTC. Items sin fecha parseable se ignoran.
    """
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # RSS 2.0
    for it in root.iter("item"):
        titulo = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        resumen = (it.findtext("description") or "").strip()
        fecha = _parse_fecha(pub)
        if fecha and titulo:
            items.append({"titulo": titulo, "link": link, "fecha": fecha, "resumen": resumen})

    # Atom 1.0
    for entry in root.findall("atom:entry", ns):
        titulo = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        link_el = entry.find("atom:link[@rel='alternate']", ns) or entry.find("atom:link", ns)
        link = link_el.get("href", "").strip() if link_el is not None else ""
        upd = entry.findtext("atom:updated", default="", namespaces=ns) or entry.findtext(
            "atom:published", default="", namespaces=ns
        )
        resumen = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        fecha = _parse_fecha(upd)
        if fecha and titulo:
            items.append({"titulo": titulo, "link": link, "fecha": fecha, "resumen": resumen})

    return items


def _parse_fecha(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    # RFC 822 (RSS 2.0): "Wed, 22 May 2026 10:00:00 GMT"
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError):
        pass
    # ISO 8601 (Atom): "2026-05-22T10:00:00Z"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _pasa_keywords(titulo: str, ctx: DetectorContext) -> bool:
    t = titulo.lower()
    if ctx.keywords_negativas and any(k.lower() in t for k in ctx.keywords_negativas):
        return False
    if ctx.keywords_obligatorias:
        return any(k.lower() in t for k in ctx.keywords_obligatorias)
    return True


# Lista codificada en CLAUDE.md §6.2 / política editorial. Pequeña por ahora;
# en producción debe venir de fuentes_configuradas.usar_solo_como_senal.
_DOMINIOS_PAYWALL = {
    "heraldo.es",
    "elperiodicodearagon.com",
    "elpais.com",
    "elmundo.es",
    "abc.es",
    "lavanguardia.com",
}


def _es_dominio_paywall(url: str) -> bool:
    host = urlparse(url).hostname or ""
    host = host.removeprefix("www.")
    return host in _DOMINIOS_PAYWALL
