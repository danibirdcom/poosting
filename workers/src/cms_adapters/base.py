"""Interfaz abstracta para adapters de CMS.

Cada adapter implementa la publicación al CMS específico del medio. Se carga
dinámicamente según ``medios.cms_tipo``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class PublishResult:
    cms_id: str
    cms_url: str


@dataclass
class MediaUpload:
    cms_id: str
    url: str


class CMSAdapter(ABC):
    """Contrato común a todos los adapters de CMS."""

    @abstractmethod
    async def publish(self, draft: dict[str, Any]) -> PublishResult: ...

    @abstractmethod
    async def update(self, cms_id: str, draft: dict[str, Any]) -> PublishResult: ...

    @abstractmethod
    async def delete(self, cms_id: str) -> None: ...

    @abstractmethod
    async def get_categories(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_tags(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def upload_media(self, file_bytes: bytes, filename: str, mime: str) -> MediaUpload: ...
