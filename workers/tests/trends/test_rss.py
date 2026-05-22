"""Tests del detector RSS: parser de feed + filtros + paywall."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.trends.rss import (
    _es_dominio_paywall,
    _pasa_keywords,
    parse_feed_items,
)
from src.trends.base import DetectorContext


def _ctx(**kwargs) -> DetectorContext:
    base = {
        "medio_id": uuid4(),
        "perfil_id": uuid4(),
        "fuente_id": uuid4(),
        "categoria_destino": "politica_local",
        "pais": "ES",
        "idiomas": ("es",),
        "keywords_obligatorias": (),
        "keywords_negativas": (),
        "config": {},
        "usar_solo_como_senal": False,
    }
    base.update(kwargs)
    return DetectorContext(**base)


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Aragón Digital</title>
    <item>
      <title>Azcón anuncia presupuesto récord en Aragón</title>
      <link>https://example.es/azcon-presupuesto</link>
      <pubDate>{fecha}</pubDate>
      <description>El presidente del Gobierno de Aragón ha presentado…</description>
    </item>
    <item>
      <title>Real Zaragoza ficha a un delantero</title>
      <link>https://example.es/zaragoza-delantero</link>
      <pubDate>{fecha}</pubDate>
      <description>Fichaje confirmado por el club.</description>
    </item>
  </channel>
</rss>
"""


ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Feed Atom</title>
  <entry>
    <title>Noticia atómica de prueba</title>
    <link rel="alternate" href="https://example.es/atom-1"/>
    <updated>{fecha}</updated>
    <summary>Resumen.</summary>
  </entry>
</feed>
"""


def _fecha_rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def test_parse_feed_rss20_extrae_items() -> None:
    fecha = _fecha_rfc822(datetime.now(tz=UTC))
    items = parse_feed_items(RSS_SAMPLE.format(fecha=fecha))
    assert len(items) == 2
    assert items[0]["titulo"].startswith("Azcón")
    assert items[0]["link"].startswith("https://")
    assert items[0]["fecha"].tzinfo is not None


def test_parse_feed_atom_extrae_items() -> None:
    fecha = (datetime.now(tz=UTC) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    items = parse_feed_items(ATOM_SAMPLE.format(fecha=fecha))
    assert len(items) == 1
    assert items[0]["titulo"] == "Noticia atómica de prueba"


def test_parse_feed_xml_invalido_devuelve_lista_vacia() -> None:
    assert parse_feed_items("<<<not xml>>>") == []
    assert parse_feed_items("") == []


def test_pasa_keywords_obligatorias() -> None:
    ctx = _ctx(keywords_obligatorias=("aragón", "zaragoza"))
    assert _pasa_keywords("Noticia sobre Aragón hoy", ctx)
    assert _pasa_keywords("La feria de Zaragoza", ctx)
    assert not _pasa_keywords("Madrid amanece soleado", ctx)


def test_pasa_keywords_negativas_bloquean() -> None:
    ctx = _ctx(keywords_negativas=("spam", "publirreportaje"))
    assert _pasa_keywords("Política aragonesa", ctx)
    assert not _pasa_keywords("Publirreportaje sobre Aragón", ctx)


def test_es_dominio_paywall_detecta_heraldo() -> None:
    assert _es_dominio_paywall("https://www.heraldo.es/feed/rss")
    assert _es_dominio_paywall("https://heraldo.es/")
    assert not _es_dominio_paywall("https://aragondigital.es/rss")
