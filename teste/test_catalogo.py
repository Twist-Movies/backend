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
from apps.movies.services import movie_stats, pick_trailer

from .helpers import criar_usuario, fake_get_movie, tmdb_movie_payload


def page(*ids):
    return {
        "page": 1, "total_pages": 1, "total_results": len(ids),
        "results": [
            {"id": i, "title": f"Filme {i}", "overview": "sinopse", "backdrop_path": "/b.jpg"}
            for i in ids
        ],
    }


class AprovacaoTests(APITestCase):
    def _stats(self, likes, dislikes):
        movie = Movie.objects.create(provider_movie_id=1, title="X")
        for i in range(likes + dislikes):
            MovieReaction.objects.create(
                user=criar_usuario(f"u{i}"), movie=movie,
                reaction="LIKE" if i < likes else "DISLIKE",
            )
        return movie_stats(movie)

    def test_menos_de_3_votos_retorna_null(self):
        stats = self._stats(2, 0)
        self.assertIsNone(stats["approval_percent"])
        self.assertEqual(stats["approval_votes"], 2)

    def test_percentual_arredondado(self):
        stats = self._stats(2, 1)
        self.assertEqual(stats["approval_percent"], 67)
        self.assertEqual(stats["approval_votes"], 3)

    def test_sem_votos(self):
        stats = self._stats(0, 0)
        self.assertIsNone(stats["approval_percent"])
        self.assertEqual(stats["approval_votes"], 0)


class DetalheDoFilmeTests(APITestCase):
    @patch("apps.movies.tmdb.get_movie")
    def test_trailer_generos_e_ids_de_pessoas(self, mock_get):
        mock_get.return_value = tmdb_movie_payload(videos={"results": [
            {"site": "Vimeo", "type": "Trailer", "key": "vimeo"},
            {"site": "YouTube", "type": "Teaser", "key": "teaser", "official": True},
            {"site": "YouTube", "type": "Trailer", "key": "naooficial", "official": False},
            {"site": "YouTube", "type": "Trailer", "key": "oficial", "official": True},
        ]})

        data = self.client.get("/api/movies/550/").data

        self.assertEqual(data["trailer"], "oficial")
        self.assertEqual(data["genres"], ["Drama"])
        self.assertEqual(data["genres_info"], [{"id": 18, "name": "Drama"}])
        self.assertEqual(data["cast"][0]["id"], 287)
        self.assertEqual(
            [(p["id"], p["job"]) for p in data["crew"]],
            [(7467, "Director"), (2, "Director of Photography")],
        )

    @patch("apps.movies.tmdb.get_movie")
    def test_sem_videos_trailer_nulo(self, mock_get):
        mock_get.return_value = tmdb_movie_payload()
        payload = tmdb_movie_payload()
        payload.pop("videos")
        self.assertIsNone(pick_trailer(payload))
        self.assertIsNone(self.client.get("/api/movies/550/").data["trailer"])

    @override_settings(TMDB_API_KEY="k", TMDB_BASE_URL="https://tmdb.test/3")
    @patch("apps.movies.tmdb.httpx.get")
    def test_get_movie_pede_videos(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"id": 7}
        cache.clear()
        tmdb.get_movie(7)
        params = mock_get.call_args.kwargs["params"]
        self.assertIn("videos", params["append_to_response"])
        self.assertEqual(params["include_video_language"], "pt,en,null")


class ListagensTMDBTests(APITestCase):
    @patch("apps.movies.tmdb.get_recommendations")
    def test_recomendacoes(self, mock_rec):
        mock_rec.return_value = page(1, 2)
        response = self.client.get("/api/movies/550/recommendations/", {"page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["tmdb_id"] for r in response.data["results"]], [1, 2])
        self.assertEqual(response.data["results"][0]["backdrop_path"], "/b.jpg")
        self.assertEqual(response.data["results"][0]["overview"], "sinopse")
        mock_rec.assert_called_once_with(550, 2)

    @patch("apps.movies.tmdb.get_similar")
    @patch("apps.movies.tmdb.get_recommendations")
    def test_recomendacoes_vazias_usam_similares(self, mock_rec, mock_sim):
        mock_rec.return_value = page()
        mock_sim.return_value = page(9)
        response = self.client.get("/api/movies/550/recommendations/")
        self.assertEqual([r["tmdb_id"] for r in response.data["results"]], [9])

    @patch("apps.movies.tmdb.get_recommendations", side_effect=tmdb.TMDBNotFound("x"))
    def test_recomendacoes_filme_inexistente(self, _):
        self.assertEqual(self.client.get("/api/movies/1/recommendations/").status_code, 404)

    @patch("apps.movies.tmdb.get_recommendations", side_effect=tmdb.TMDBError("x"))
    def test_recomendacoes_tmdb_fora(self, _):
        self.assertEqual(self.client.get("/api/movies/1/recommendations/").status_code, 503)

    @patch("apps.movies.tmdb.get_trending")
    def test_tendencias(self, mock_trending):
        mock_trending.return_value = page(5)
        response = self.client.get("/api/movies/trending/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["tmdb_id"], 5)
        mock_trending.assert_called_once_with(1)

    @patch("apps.movies.tmdb.get_trending", side_effect=tmdb.TMDBError("x"))
    def test_tendencias_tmdb_fora(self, _):
        self.assertEqual(self.client.get("/api/movies/trending/").status_code, 503)

    def test_pagina_invalida(self):
        self.assertEqual(self.client.get("/api/movies/trending/", {"page": 0}).status_code, 400)


class PessoaTests(APITestCase):
    def _person(self, biography="Bio"):
        return {
            "id": 287, "name": "Brad Pitt", "biography": biography, "birthday": "1963-12-18",
            "place_of_birth": "Oklahoma", "known_for_department": "Acting", "profile_path": "/p.jpg",
            "movie_credits": {"cast": [
                {"id": i, "title": f"F{i}", "popularity": i} for i in range(1, 26)
            ]},
        }

    @patch("apps.movies.tmdb.get_person")
    def test_pessoa(self, mock_person):
        mock_person.return_value = self._person()
        data = self.client.get("/api/people/287/").data
        self.assertEqual(data["name"], "Brad Pitt")
        self.assertEqual(data["biography"], "Bio")
        self.assertEqual(len(data["movies"]), 20)
        self.assertEqual(data["movies"][0]["tmdb_id"], 25)
        self.assertEqual(set(data), {
            "id", "name", "biography", "birthday", "place_of_birth",
            "known_for_department", "profile_path", "movies",
        })

    @patch("apps.movies.tmdb.get_person")
    def test_biografia_vazia_usa_fallback_em_ingles(self, mock_person):
        mock_person.side_effect = [self._person(""), self._person("English bio")]
        data = self.client.get("/api/people/287/").data
        self.assertEqual(data["biography"], "English bio")
        self.assertEqual(mock_person.call_args_list[1].kwargs, {"language": "en-US"})

    @patch("apps.movies.tmdb.get_person", side_effect=tmdb.TMDBNotFound("x"))
    def test_pessoa_inexistente(self, _):
        self.assertEqual(self.client.get("/api/people/1/").status_code, 404)

    @patch("apps.movies.tmdb.get_person", side_effect=tmdb.TMDBError("x"))
    def test_tmdb_fora(self, _):
        self.assertEqual(self.client.get("/api/people/1/").status_code, 503)


class ListasOficiaisTests(APITestCase):
    def test_lista_apenas_playlists_publicas_do_twist_staff(self):
        twist = criar_usuario("twist", is_staff=True)
        impostor = criar_usuario("outro")
        Playlist.objects.create(owner=twist, name="Oficial")
        Playlist.objects.create(owner=twist, name="Rascunho", is_public=False)
        Playlist.objects.create(owner=impostor, name="Comum")

        response = self.client.get("/api/playlists/official/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["name"] for p in response.data["results"]], ["Oficial"])
        self.assertEqual(response.data["count"], 1)

    def test_detalhe_de_playlist_publica_de_outro_dono(self):
        twist = criar_usuario("twist", is_staff=True)
        playlist = Playlist.objects.create(owner=twist, name="Oficial")
        self.client.force_authenticate(criar_usuario("leitor"))
        self.assertEqual(self.client.get(f"/api/playlists/{playlist.id}/").status_code, 200)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"/api/playlists/{playlist.id}/").status_code, 200)

    @patch("apps.movies.tmdb.get_movie", side_effect=fake_get_movie)
    def test_seed_e_idempotente(self, _):
        call_command("seed_listas_oficiais", stdout=StringIO())
        call_command("seed_listas_oficiais", stdout=StringIO())

        twist = Playlist.objects.first().owner
        self.assertEqual(twist.username, "twist")
        self.assertTrue(twist.is_staff)
        self.assertEqual(twist.email, "twist@twist.app")
        self.assertFalse(twist.has_usable_password())
        self.assertEqual(Playlist.objects.count(), 5)
        playlist = Playlist.objects.get(name="Clássicos essenciais")
        self.assertEqual(playlist.playlist_movies.count(), 10)
        self.assertEqual(
            list(playlist.playlist_movies.order_by("position").values_list("position", flat=True)),
            list(range(10)),
        )

    @patch("apps.movies.tmdb.get_movie")
    def test_seed_tolera_erro_do_tmdb(self, mock_get):
        def side(tmdb_id):
            if tmdb_id == 238:
                raise tmdb.TMDBNotFound("x")
            return fake_get_movie(tmdb_id)

        mock_get.side_effect = side
        err = StringIO()
        call_command("seed_listas_oficiais", stdout=StringIO(), stderr=err)
        self.assertIn("238", err.getvalue())
        self.assertEqual(Playlist.objects.get(name="Clássicos essenciais").playlist_movies.count(), 9)
        self.assertFalse(PlaylistMovie.objects.filter(movie__provider_movie_id=238).exists())


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
