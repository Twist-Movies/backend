"""
Testes dos endpoints de filmes:

    GET          /api/movies/search/
    GET          /api/movies/{tmdb_id}/
    POST/DELETE  /api/movies/{tmdb_id}/watch/
    POST/DELETE  /api/movies/{tmdb_id}/watchlist/
    PUT/PATCH/DELETE /api/movies/{tmdb_id}/rating/
    PUT/DELETE   /api/movies/{tmdb_id}/reaction/

O TMDB é sempre mockado: nenhuma chamada de rede real é feita.

Executar com:
    DJANGO_SETTINGS_MODULE=config.settings.testing python manage.py test teste
"""
from unittest.mock import MagicMock, patch

import httpx
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.movies import tmdb
from apps.movies.models import Movie, MovieReaction, Rating, WatchedMovie, Watchlist

from .helpers import criar_usuario, fake_get_movie, tmdb_movie_payload

SEARCH_URL = "/api/movies/search/"


def movie_url(tmdb_id, suffix=""):
    return f"/api/movies/{tmdb_id}/{suffix}"


@override_settings(TMDB_API_KEY="chave-v3", TMDB_BASE_URL="https://tmdb.test/3")
class TMDBClientTests(TestCase):
    def setUp(self):
        cache.clear()

    def _response(self, status_code=200, json_data=None):
        response = MagicMock(status_code=status_code)
        response.json.return_value = json_data if json_data is not None else {}
        return response

    @patch("apps.movies.tmdb.httpx.get")
    def test_api_key_v3_vai_como_query_param(self, mock_get):
        mock_get.return_value = self._response(json_data={"id": 550})

        tmdb.get_movie(550)

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["api_key"], "chave-v3")
        self.assertNotIn("Authorization", kwargs["headers"])

    @override_settings(TMDB_API_KEY="eyJtoken-v4")
    @patch("apps.movies.tmdb.httpx.get")
    def test_token_v4_vai_no_header(self, mock_get):
        mock_get.return_value = self._response(json_data={"id": 550})

        tmdb.get_movie(550)

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer eyJtoken-v4")
        self.assertNotIn("api_key", kwargs["params"])

    @patch("apps.movies.tmdb.httpx.get")
    def test_respostas_sao_cacheadas(self, mock_get):
        mock_get.return_value = self._response(json_data={"results": []})

        tmdb.search_movies("matrix")
        tmdb.search_movies("matrix")

        mock_get.assert_called_once()

    @patch("apps.movies.tmdb.httpx.get")
    def test_404_vira_tmdb_not_found(self, mock_get):
        mock_get.return_value = self._response(status_code=404)
        with self.assertRaises(tmdb.TMDBNotFound):
            tmdb.get_movie(999999)

    @patch("apps.movies.tmdb.httpx.get")
    def test_429_vira_tmdb_error(self, mock_get):
        mock_get.return_value = self._response(status_code=429)
        with self.assertRaises(tmdb.TMDBError):
            tmdb.get_movie(550)

    @patch("apps.movies.tmdb.httpx.get", side_effect=httpx.ConnectError("offline"))
    def test_erro_de_rede_vira_tmdb_error(self, _):
        with self.assertRaises(tmdb.TMDBError):
            tmdb.get_movie(550)

    @override_settings(TMDB_API_KEY="")
    def test_sem_chave_configurada(self):
        with self.assertRaises(tmdb.TMDBError):
            tmdb.get_movie(550)


class MovieSearchTests(APITestCase):
    @patch("apps.movies.tmdb.search_movies")
    def test_busca_retorna_resultados_normalizados(self, mock_search):
        mock_search.return_value = {
            "page": 1,
            "total_pages": 1,
            "total_results": 1,
            "results": [{"id": 603, "title": "Matrix", "release_date": "", "vote_average": 8.2}],
        }

        response = self.client.get(SEARCH_URL, {"q": "matrix"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["tmdb_id"], 603)
        self.assertIsNone(response.data["results"][0]["release_date"])
        mock_search.assert_called_once_with("matrix", 1)

    def test_busca_sem_q_retorna_400(self):
        response = self.client.get(SEARCH_URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("q", response.data)

    @patch("apps.movies.tmdb.search_movies", side_effect=tmdb.TMDBError("fora do ar"))
    def test_busca_com_tmdb_indisponivel_retorna_503(self, _):
        response = self.client.get(SEARCH_URL, {"q": "matrix"})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)


class MovieDetailTests(APITestCase):
    @patch("apps.movies.tmdb.get_movie")
    def test_detalhe_sincroniza_filme_local(self, mock_get_movie):
        mock_get_movie.return_value = tmdb_movie_payload()

        response = self.client.get(movie_url(550))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        movie = Movie.objects.get(provider_movie_id=550)
        self.assertEqual(response.data["id"], movie.id)
        self.assertEqual(response.data["certification"], "18")
        self.assertEqual(response.data["genres"], ["Drama"])
        self.assertEqual([p["name"] for p in response.data["crew"]], ["David Fincher"])
        self.assertIsNone(response.data["user_state"])

    @patch("apps.movies.tmdb.get_movie")
    def test_detalhe_nao_duplica_filme(self, mock_get_movie):
        mock_get_movie.return_value = tmdb_movie_payload()

        self.client.get(movie_url(550))
        self.client.get(movie_url(550))

        self.assertEqual(Movie.objects.filter(provider_movie_id=550).count(), 1)

    @patch("apps.movies.tmdb.get_movie")
    def test_detalhe_inclui_contadores_e_estado_do_usuario(self, mock_get_movie):
        mock_get_movie.return_value = tmdb_movie_payload()
        user = criar_usuario()
        outro = criar_usuario("outro")
        self.client.get(movie_url(550))
        movie = Movie.objects.get(provider_movie_id=550)
        MovieReaction.objects.create(user=user, movie=movie, reaction="LIKE")
        MovieReaction.objects.create(user=outro, movie=movie, reaction="DISLIKE")
        Rating.objects.create(user=user, movie=movie, stars=5)
        Rating.objects.create(user=outro, movie=movie, stars=2)
        WatchedMovie.objects.create(user=user, movie=movie)

        self.client.force_authenticate(user)
        response = self.client.get(movie_url(550))

        stats = response.data["stats"]
        self.assertEqual(stats["likes_count"], 1)
        self.assertEqual(stats["dislikes_count"], 1)
        self.assertEqual(stats["watched_count"], 1)
        self.assertEqual(stats["rating_average"], 3.5)
        self.assertEqual(stats["rating_count"], 2)
        self.assertEqual(
            response.data["user_state"],
            {"watched": True, "in_watchlist": False, "reaction": "LIKE", "rating": 5.0},
        )

    @patch("apps.movies.tmdb.get_movie", side_effect=tmdb.TMDBNotFound("não existe"))
    def test_filme_inexistente_retorna_404(self, _):
        response = self.client.get(movie_url(999999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@patch("apps.movies.tmdb.get_movie", side_effect=fake_get_movie)
class WatchedAndWatchlistTests(APITestCase):
    def setUp(self):
        self.user = criar_usuario()
        self.client.force_authenticate(self.user)

    def test_requer_autenticacao(self, _):
        self.client.force_authenticate(None)
        for suffix in ("watch/", "watchlist/"):
            response = self.client.post(movie_url(550, suffix))
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_marcar_assistido_e_idempotente(self, _):
        first = self.client.post(movie_url(550, "watch/"))
        second = self.client.post(movie_url(550, "watch/"))

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(WatchedMovie.objects.filter(user=self.user).count(), 1)

    def test_remover_assistido(self, _):
        self.client.post(movie_url(550, "watch/"))

        response = self.client.delete(movie_url(550, "watch/"))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(WatchedMovie.objects.exists())

    def test_remover_assistido_inexistente_retorna_404(self, _):
        response = self.client.delete(movie_url(550, "watch/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_adicionar_e_remover_da_watchlist(self, _):
        added = self.client.post(movie_url(550, "watchlist/"))
        self.assertEqual(added.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Watchlist.objects.filter(user=self.user).exists())

        removed = self.client.delete(movie_url(550, "watchlist/"))
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Watchlist.objects.exists())

    def test_filme_inexistente_no_tmdb_retorna_404(self, mock_get_movie):
        mock_get_movie.side_effect = tmdb.TMDBNotFound("não existe")
        response = self.client.post(movie_url(999999, "watch/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Movie.objects.exists())


@patch("apps.movies.tmdb.get_movie", side_effect=fake_get_movie)
class RatingTests(APITestCase):
    def setUp(self):
        self.user = criar_usuario()
        self.client.force_authenticate(self.user)

    def test_avaliar_e_alterar_avaliacao(self, _):
        created = self.client.put(movie_url(550, "rating/"), {"stars": 4}, format="json")
        updated = self.client.patch(movie_url(550, "rating/"), {"stars": 2}, format="json")

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(Rating.objects.get(user=self.user).stars, 2)
        self.assertEqual(Rating.objects.count(), 1)

    def test_nota_fora_da_escala_retorna_400(self, _):
        for stars in (0, 6, 5.5, 0.7, 0.25, "abc"):
            response = self.client.put(movie_url(550, "rating/"), {"stars": stars}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, stars)
        self.assertFalse(Rating.objects.exists())

    def test_aceita_meia_estrela_e_devolve_float(self, _):
        response = self.client.put(movie_url(550, "rating/"), {"stars": 4.5}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsInstance(response.data["stars"], float)
        self.assertEqual(response.data["stars"], 4.5)
        self.assertEqual(float(Rating.objects.get(user=self.user).stars), 4.5)
        for stars in (0.5, 5, 1):
            ok = self.client.put(movie_url(550, "rating/"), {"stars": stars}, format="json")
            self.assertEqual(ok.status_code, status.HTTP_200_OK, stars)

    def test_estado_do_usuario_e_media_sao_numeros(self, mock_get_movie):
        self.client.put(movie_url(550, "rating/"), {"stars": 4.5}, format="json")
        outro = criar_usuario("outro")
        self.client.force_authenticate(outro)
        self.client.put(movie_url(550, "rating/"), {"stars": 3}, format="json")

        response = self.client.get(movie_url(550))

        self.assertEqual(response.data["user_state"]["rating"], 3.0)
        self.assertIsInstance(response.data["user_state"]["rating"], float)
        self.assertEqual(response.data["stats"]["rating_average"], 3.75)
        self.assertIsInstance(response.data["stats"]["rating_average"], float)

    def test_remover_avaliacao(self, _):
        self.client.put(movie_url(550, "rating/"), {"stars": 4}, format="json")

        response = self.client.delete(movie_url(550, "rating/"))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Rating.objects.exists())


@patch("apps.movies.tmdb.get_movie", side_effect=fake_get_movie)
class ReactionTests(APITestCase):
    def setUp(self):
        self.user = criar_usuario()
        self.client.force_authenticate(self.user)

    def test_curtir_e_trocar_para_deslike_mantem_uma_reacao(self, _):
        liked = self.client.put(movie_url(550, "reaction/"), {"reaction": "LIKE"}, format="json")
        disliked = self.client.put(movie_url(550, "reaction/"), {"reaction": "DISLIKE"}, format="json")

        self.assertEqual(liked.status_code, status.HTTP_201_CREATED)
        self.assertEqual(disliked.status_code, status.HTTP_200_OK)
        self.assertEqual(MovieReaction.objects.filter(user=self.user).count(), 1)
        self.assertEqual(MovieReaction.objects.get(user=self.user).reaction, "DISLIKE")

    def test_reacao_invalida_retorna_400(self, _):
        response = self.client.put(movie_url(550, "reaction/"), {"reaction": "LOVE"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remover_reacao(self, _):
        self.client.put(movie_url(550, "reaction/"), {"reaction": "LIKE"}, format="json")

        response = self.client.delete(movie_url(550, "reaction/"))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(MovieReaction.objects.exists())
