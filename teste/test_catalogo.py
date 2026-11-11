"""Testes de aprovação, trailer, recomendações, tendências, pessoas e listas oficiais (TMDB sempre mockado)."""
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APITestCase

from apps.movies import tmdb
from apps.movies.models import Movie, MovieReaction, Playlist, PlaylistMovie
from apps.movies.services import movie_stats

from .helpers import criar_usuario, fake_get_movie, tmdb_movie_payload


def page(*ids):
    return {
        "page": 1, "total_pages": 1, "total_results": len(ids),
        "results": [
            {"id": i, "title": f"Filme {i}", "overview": "sinopse", "backdrop_path": "/b.jpg"}
            for i in ids
        ],
    }
class MigracaoMeiaEstrelaTests(TransactionTestCase):
    def test_notas_inteiras_sao_preservadas(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("movies", "0001_initial")])
        old = executor.loader.project_state([("movies", "0001_initial")]).apps
        user = old.get_model("accounts", "User").objects.create(username="m", email="m@example.com")
        movie = old.get_model("movies", "Movie").objects.create(provider_movie_id=1, title="X")
        old.get_model("movies", "Rating").objects.create(user=user, movie=movie, stars=4)

        executor = MigrationExecutor(connection)
        executor.migrate([("movies", "0002_rating_meia_estrela")])

        from apps.movies.models import Rating
        self.assertEqual(float(Rating.objects.get().stars), 4.0)
        Rating.objects.update(stars=0.5)
        self.assertEqual(float(Rating.objects.get().stars), 0.5)
