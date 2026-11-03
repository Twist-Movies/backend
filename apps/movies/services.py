from django.db.models import Avg, Count, Q
from django.utils.dateparse import parse_date
from django.utils import timezone
from . import tmdb
from .models import Movie, MovieReaction, Rating, WatchedMovie, Watchlist

TMDB_PROVIDER = "TMDB"

DISCOVER_SORTS = {
    "popularity": "popularity.desc",
    "rating": "vote_average.desc",
    "release_date": "primary_release_date.desc",
}


def build_discover_params(filters):
    """Traduz os filtros do Twist para os parâmetros do /discover/movie do TMDB."""
    sort = filters.get("sort", "popularity")
    params = {"sort_by": DISCOVER_SORTS[sort]}

    if sort == "rating":
        # Sem um mínimo de votos, aparecem filmes obscuros com um único voto nota 10.
        params["vote_count.gte"] = 300
    if sort == "release_date":
        # Sem o limite de hoje, os primeiros resultados seriam filmes ainda não lançados.
        params["primary_release_date.lte"] = timezone.localdate().isoformat()
        params["vote_count.gte"] = 20

    if "genre" in filters:
        params["with_genres"] = filters["genre"]

    if "decade" in filters:
        year = filters["decade"]
        decade_end = f"{year + 9}-12-31"
        params["primary_release_date.gte"] = f"{year}-01-01"
        # Datas ISO comparam corretamente como texto: vale o menor entre o fim da década e hoje.
        params["primary_release_date.lte"] = min(
            decade_end, params.get("primary_release_date.lte", decade_end)
        )

    if "runtime_min" in filters:
        params["with_runtime.gte"] = filters["runtime_min"]
    if "runtime_max" in filters:
        params["with_runtime.lte"] = filters["runtime_max"]

    if "rating_min" in filters:
        params["vote_average.gte"] = filters["rating_min"]
        params.setdefault("vote_count.gte", 100)

    return params


def serialize_search_page(data):
    """Formato de resposta compartilhado pela busca e pelo discover (os cartões do front são os mesmos)."""
    return {
        "page": data.get("page", 1),
        "total_pages": data.get("total_pages", 0),
        "total_results": data.get("total_results", 0),
        "results": [
            {
                "tmdb_id": item.get("id"),
                "title": item.get("title"),
                "original_title": item.get("original_title"),
                "overview": item.get("overview"),
                "poster_path": item.get("poster_path"),
                "backdrop_path": item.get("backdrop_path"),
                "release_date": item.get("release_date") or None,
                "tmdb_rating_average": item.get("vote_average"),
            }
            for item in data.get("results") or []
        ],
    }

def sync_movie(data):
    """Cria ou atualiza o filme local a partir do payload de detalhes do TMDB."""
    movie, _ = Movie.objects.update_or_create(
        provider=TMDB_PROVIDER,
        provider_movie_id=data["id"],
        defaults={
            "title": data.get("title") or data.get("original_title") or "",
            "original_title": data.get("original_title"),
            "overview": data.get("overview") or None,
            "poster_path": data.get("poster_path"),
            "backdrop_path": data.get("backdrop_path"),
            "release_date": parse_date(data.get("release_date") or ""),
            "runtime_minutes": data.get("runtime") or None,
            "rating_average": data.get("vote_average"),
            "rating_count": data.get("vote_count") or 0,
        },
    )
    return movie


def get_or_sync_movie(tmdb_id):
    """Garante que o filme exista no catálogo local (RN02) antes de ser associado
    a avaliações, resenhas, reações ou playlists.

    Lança tmdb.TMDBNotFound se o id não existir no TMDB.
    """
    movie = Movie.objects.filter(provider=TMDB_PROVIDER, provider_movie_id=tmdb_id).first()
    if movie is not None:
        return movie
    return sync_movie(tmdb.get_movie(tmdb_id))


def get_local_movie(tmdb_id):
    """Retorna o filme local ou None, sem consultar o TMDB."""
    return Movie.objects.filter(provider=TMDB_PROVIDER, provider_movie_id=tmdb_id).first()


def movie_stats(movie):
    reactions = MovieReaction.objects.filter(movie=movie).aggregate(
        likes=Count("id", filter=Q(reaction=MovieReaction.ReactionChoices.LIKE)),
        dislikes=Count("id", filter=Q(reaction=MovieReaction.ReactionChoices.DISLIKE)),
    )
    ratings = Rating.objects.filter(movie=movie).aggregate(average=Avg("stars"), count=Count("id"))
    average = ratings["average"]
    return {
        "likes_count": reactions["likes"],
        "dislikes_count": reactions["dislikes"],
        "watched_count": WatchedMovie.objects.filter(movie=movie).count(),
        "rating_average": round(average, 2) if average is not None else None,
        "rating_count": ratings["count"],
    }


def user_movie_state(user, movie):
    if not user.is_authenticated:
        return None
    reaction = MovieReaction.objects.filter(user=user, movie=movie).values_list("reaction", flat=True).first()
    stars = Rating.objects.filter(user=user, movie=movie).values_list("stars", flat=True).first()
    return {
        "watched": WatchedMovie.objects.filter(user=user, movie=movie).exists(),
        "in_watchlist": Watchlist.objects.filter(user=user, movie=movie).exists(),
        "reaction": reaction,
        "rating": stars,
    }


def _certification(data):
    """Classificação indicativa: prioriza o Brasil e cai para os EUA."""
    results = (data.get("release_dates") or {}).get("results") or []
    by_country = {item.get("iso_3166_1"): item.get("release_dates") or [] for item in results}
    for country in ("BR", "US"):
        for release in by_country.get(country, []):
            if release.get("certification"):
                return release["certification"]
    return None


def build_movie_detail(data, movie, user):
    credits = data.get("credits") or {}
    return {
        "id": movie.id,
        "tmdb_id": movie.provider_movie_id,
        "title": movie.title,
        "original_title": movie.original_title,
        "overview": movie.overview,
        "poster_path": movie.poster_path,
        "backdrop_path": movie.backdrop_path,
        "release_date": movie.release_date,
        "runtime_minutes": movie.runtime_minutes,
        "certification": _certification(data),
        "genres": [genre["name"] for genre in data.get("genres") or []],
        "cast": [
            {
                "name": person.get("name"),
                "character": person.get("character"),
                "profile_path": person.get("profile_path"),
            }
            for person in (credits.get("cast") or [])[:15]
        ],
        "crew": [
            {
                "name": person.get("name"),
                "job": person.get("job"),
                "profile_path": person.get("profile_path"),
            }
            for person in credits.get("crew") or []
            if person.get("job") in ("Director", "Screenplay", "Writer", "Producer", "Original Music Composer")
        ],
        "tmdb_rating_average": movie.rating_average,
        "tmdb_rating_count": movie.rating_count,
        "stats": movie_stats(movie),
        "user_state": user_movie_state(user, movie),
    }
