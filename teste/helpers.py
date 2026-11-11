"""Utilitários compartilhados pelos testes dos endpoints de filmes."""
from django.contrib.auth import get_user_model

User = get_user_model()

STRONG_PASSWORD = "Tw1st!Senha#Forte"


def criar_usuario(username="usuario", **extra):
    return User.objects.create_user(
        username=username,
        email=extra.pop("email", f"{username}@example.com"),
        password=STRONG_PASSWORD,
        **extra,
    )


def tmdb_movie_payload(tmdb_id=550, title="Clube da Luta", **overrides):
    """Payload no formato de GET /movie/{id}?append_to_response=credits,release_dates."""
    data = {
        "id": tmdb_id,
        "title": title,
        "original_title": "Fight Club",
        "overview": "Um homem deprimido conhece um vendedor de sabão.",
        "poster_path": "/poster.jpg",
        "backdrop_path": "/backdrop.jpg",
        "release_date": "1999-10-15",
        "runtime": 139,
        "vote_average": 8.4,
        "vote_count": 30000,
        "genres": [{"id": 18, "name": "Drama"}],
        "videos": {"results": []},
        "credits": {
            "cast": [{"id": 287, "name": "Brad Pitt", "character": "Tyler Durden", "profile_path": "/brad.jpg"}],
            "crew": [
                {"id": 7467, "name": "David Fincher", "job": "Director", "profile_path": None},
                {"id": 1, "name": "Fulano", "job": "Catering", "profile_path": None},
                {"id": 2, "name": "Jeff", "job": "Director of Photography", "profile_path": None},
            ],
        },
        "release_dates": {
            "results": [
                {"iso_3166_1": "US", "release_dates": [{"certification": "R"}]},
                {"iso_3166_1": "BR", "release_dates": [{"certification": "18"}]},
            ]
        },
    }
    data.update(overrides)
    return data


def fake_get_movie(tmdb_id):
    return tmdb_movie_payload(tmdb_id=tmdb_id, title=f"Filme {tmdb_id}")
