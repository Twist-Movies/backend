"""
Testes dos endpoints de comentários:

    GET/POST     /api/movies/{tmdb_id}/reviews/
    GET/PATCH/DELETE /api/reviews/{id}/
    POST/DELETE  /api/reviews/{id}/like/

O TMDB é sempre mockado: nenhuma chamada de rede real é feita.

Executar com:
    DJANGO_SETTINGS_MODULE=config.settings.testing python manage.py test teste
"""
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from apps.movies import tmdb
from apps.movies.models import Review, ReviewLike

from .helpers import criar_usuario, fake_get_movie


def reviews_url(tmdb_id=550):
    return f"/api/movies/{tmdb_id}/reviews/"


def review_url(review_id, suffix=""):
    return f"/api/reviews/{review_id}/{suffix}"


@patch("apps.movies.tmdb.get_movie", side_effect=fake_get_movie)
class ReviewTests(APITestCase):
    def setUp(self):
        self.autor = criar_usuario("autor")
        self.outro = criar_usuario("outro")
        self.client.force_authenticate(self.autor)

    def _criar_resenha(self, tmdb_id=550, **data):
        payload = {"content": "Filmaço.", "contains_spoiler": False, **data}
        return self.client.post(reviews_url(tmdb_id), payload, format="json")

    def test_criar_resenha(self, _):
        response = self._criar_resenha(contains_spoiler=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["author"]["username"], "autor")
        self.assertEqual(response.data["movie"]["tmdb_id"], 550)
        self.assertTrue(response.data["contains_spoiler"])
        self.assertEqual(response.data["likes_count"], 0)

    def test_criar_resenha_requer_autenticacao(self, _):
        self.client.force_authenticate(None)
        response = self._criar_resenha()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_conteudo_vazio_retorna_400(self, _):
        response = self._criar_resenha(content="   ")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("content", response.data)

    def test_apenas_uma_resenha_ativa_por_filme(self, _):
        self._criar_resenha()
        response = self._criar_resenha(content="Outra opinião.")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Review.objects.filter(user=self.autor).count(), 1)

    def test_pode_criar_nova_resenha_apos_excluir(self, _):
        review_id = self._criar_resenha().data["id"]
        self.client.delete(review_url(review_id))

        response = self._criar_resenha(content="Mudei de ideia.")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_filme_inexistente_retorna_404(self, mock_get_movie):
        mock_get_movie.side_effect = tmdb.TMDBNotFound("não existe")
        response = self._criar_resenha(tmdb_id=999999)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_listar_resenhas_do_filme_e_publico(self, _):
        self._criar_resenha()
        self.client.force_authenticate(self.outro)
        self._criar_resenha(content="Não gostei.")
        self._criar_resenha(tmdb_id=603, content="De outro filme.")

        self.client.force_authenticate(None)
        response = self.client.get(reviews_url(550))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["results"][0]["content"], "Não gostei.")

    def test_listar_resenhas_de_filme_sem_registro_retorna_vazio(self, _):
        response = self.client.get(reviews_url(12345))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_autor_edita_resenha(self, _):
        review_id = self._criar_resenha().data["id"]

        response = self.client.patch(review_url(review_id), {"content": "Revisado."}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Review.objects.get(pk=review_id).content, "Revisado.")

    def test_put_nao_e_permitido(self, _):
        review_id = self._criar_resenha().data["id"]
        response = self.client.put(review_url(review_id), {"content": "x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_outro_usuario_nao_edita_nem_exclui(self, _):
        review_id = self._criar_resenha().data["id"]
        self.client.force_authenticate(self.outro)

        patched = self.client.patch(review_url(review_id), {"content": "Hackeado."}, format="json")
        deleted = self.client.delete(review_url(review_id))

        self.assertEqual(patched.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(deleted.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Review.objects.get(pk=review_id).is_active)

    def test_exclusao_e_logica_e_some_das_listagens(self, _):
        review_id = self._criar_resenha().data["id"]

        response = self.client.delete(review_url(review_id))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Review.objects.get(pk=review_id).is_active)
        self.assertEqual(self.client.get(review_url(review_id)).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(reviews_url()).data["count"], 0)


@patch("apps.movies.tmdb.get_movie", side_effect=fake_get_movie)
class ReviewLikeTests(APITestCase):
    def setUp(self):
        self.autor = criar_usuario("autor")
        self.leitor = criar_usuario("leitor")
        self.client.force_authenticate(self.autor)
        # O patch de classe só cobre os métodos test_*, não o setUp.
        with patch("apps.movies.tmdb.get_movie", side_effect=fake_get_movie):
            self.review_id = self.client.post(reviews_url(), {"content": "Filmaço."}, format="json").data["id"]
        self.client.force_authenticate(self.leitor)

    def test_curtir_resenha_uma_unica_vez(self, _):
        first = self.client.post(review_url(self.review_id, "like/"))
        second = self.client.post(review_url(self.review_id, "like/"))

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["likes_count"], 1)
        self.assertEqual(ReviewLike.objects.count(), 1)

    def test_curtida_aparece_na_resenha(self, _):
        self.client.post(review_url(self.review_id, "like/"))

        response = self.client.get(review_url(self.review_id))

        self.assertEqual(response.data["likes_count"], 1)
        self.assertTrue(response.data["liked_by_me"])

    def test_remover_curtida(self, _):
        self.client.post(review_url(self.review_id, "like/"))

        response = self.client.delete(review_url(self.review_id, "like/"))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ReviewLike.objects.exists())

    def test_remover_curtida_inexistente_retorna_404(self, _):
        response = self.client.delete(review_url(self.review_id, "like/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_nao_curte_resenha_excluida(self, _):
        Review.objects.filter(pk=self.review_id).update(is_active=False)
        response = self.client.post(review_url(self.review_id, "like/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_curtir_requer_autenticacao(self, _):
        self.client.force_authenticate(None)
        response = self.client.post(review_url(self.review_id, "like/"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
