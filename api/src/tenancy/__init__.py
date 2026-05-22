"""Resolución del tenant actual a partir del usuario autenticado."""

from .context import RequestContext, get_request_context

__all__ = ["RequestContext", "get_request_context"]
