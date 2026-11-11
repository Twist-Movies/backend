"""Throttles do projeto: todos contam no cache `ratelimit` (compartilhado via banco)."""
from django.core.cache import caches
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle


class RatelimitCacheMixin:
    @property
    def cache(self):
        return caches["ratelimit"]


class AnonThrottle(RatelimitCacheMixin, AnonRateThrottle):
    """Limite global por IP para requisições anônimas (escopo `anon`)."""


class UserThrottle(RatelimitCacheMixin, UserRateThrottle):
    """Limite global por usuário autenticado (escopo `user`)."""


class ScopedThrottle(RatelimitCacheMixin, ScopedRateThrottle):
    """Limite por IP nas views que definem `throttle_scope`."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
