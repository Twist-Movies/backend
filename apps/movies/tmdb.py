"""Cliente da API do TMDB (https://developer.themoviedb.org/reference).

Todas as chamadas externas ao TMDB passam por aqui, para que o restante da
aplicação lide apenas com dicionários já normalizados e com as exceções
definidas neste módulo.
"""
import hashlib
import json
import logging

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class TMDBError(Exception):
    """Falha de comunicação com o TMDB (rede, limite de requisições, 5xx...)."""


class TMDBNotFound(TMDBError):
    """O recurso solicitado não existe no TMDB."""


def _auth():
    """Retorna (headers, params) de autenticação.

    O Read Access Token (v4) é um JWT e vai no header Authorization;
    a API Key (v3) vai como query param.
    """
    key = settings.TMDB_API_KEY
    if not key:
        raise TMDBError("TMDB_API_KEY não configurada.")
    if key.startswith("eyJ"):
        return {"Authorization": f"Bearer {key}"}, {}
    return {}, {"api_key": key}


def _get(path, params=None):
    params = {"language": settings.TMDB_LANGUAGE, **(params or {})}

    cache_key = "tmdb:" + hashlib.sha256(
        (path + json.dumps(params, sort_keys=True)).encode()
    ).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    headers, auth_params = _auth()
    try:
        response = httpx.get(
            f"{settings.TMDB_BASE_URL}{path}",
            params={**params, **auth_params},
            headers={"Accept": "application/json", **headers},
            timeout=settings.TMDB_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("Erro de rede ao consultar o TMDB (%s): %s", path, exc)
        raise TMDBError("Não foi possível se comunicar com o TMDB.") from exc

    if response.status_code == 404:
        raise TMDBNotFound("Recurso não encontrado no TMDB.")
    if response.status_code == 429:
        logger.warning("Limite de requisições do TMDB atingido (%s).", path)
        raise TMDBError("Limite de requisições do TMDB atingido. Tente novamente em instantes.")
    if response.status_code >= 400:
        logger.error("TMDB respondeu %s para %s.", response.status_code, path)
        raise TMDBError("O TMDB está indisponível no momento.")

    try:
        data = response.json()
    except ValueError as exc:
        logger.error("Resposta inválida do TMDB para %s.", path)
        raise TMDBError("Resposta inválida do TMDB.") from exc

    cache.set(cache_key, data, settings.TMDB_CACHE_SECONDS)
    return data


def search_movies(query, page=1):
    return _get("/search/movie", {"query": query, "page": page, "include_adult": "false"})


def get_movie(tmdb_id):
    return _get(
        f"/movie/{tmdb_id}",
        {
            "append_to_response": "credits,release_dates,videos",
            # Sem isso, só vêm vídeos no idioma da requisição (pt-BR), que quase nunca tem trailer.
            "include_video_language": "pt,en,null",
        },
    )


def get_recommendations(tmdb_id, page=1):
    return _get(f"/movie/{tmdb_id}/recommendations", {"page": page})


def get_similar(tmdb_id, page=1):
    return _get(f"/movie/{tmdb_id}/similar", {"page": page})


def get_trending(page=1):
    return _get("/trending/movie/week", {"page": page})


def get_person(person_id, language=None):
    params = {"append_to_response": "movie_credits"}
    if language:
        params["language"] = language
    return _get(f"/person/{person_id}", params)


def discover_movies(params, page=1):
    return _get("/discover/movie", {**params, "page": page, "include_adult": "false"})