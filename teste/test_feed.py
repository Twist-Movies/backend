"""Testes do feed, dos comentários por usuário e da busca de usuários."""
from rest_framework.test import APITestCase

from apps.accounts.models import Follow
from apps.movies.models import Movie, Review

from .helpers import criar_usuario


class FeedTests(APITestCase):
    def setUp(self):
        self.eu = criar_usuario("eu")
        self.amigo = criar_usuario("amigo")
        self.estranho = criar_usuario("estranho")
        Follow.objects.create(follower=self.eu, following=self.amigo)
        self.f1 = Movie.objects.create(provider_movie_id=1, title="Um", poster_path="/1.jpg")
        self.f2 = Movie.objects.create(provider_movie_id=2, title="Dois")

    def test_requer_autenticacao(self):
        self.assertEqual(self.client.get("/api/feed/").status_code, 401)

    def test_feed_so_tem_resenhas_ativas_de_quem_sigo(self):
        antiga = Review.objects.create(user=self.amigo, movie=self.f1, content="a")
        nova = Review.objects.create(user=self.amigo, movie=self.f2, content="b")
        Review.objects.create(user=self.estranho, movie=self.f1, content="c")
        Review.objects.create(user=self.eu, movie=self.f1, content="d")
        f3 = Movie.objects.create(provider_movie_id=3, title="T")
        Review.objects.create(user=self.amigo, movie=f3, content="e", is_active=False)
        self.client.force_authenticate(self.eu)

        with self.assertNumQueries(2):  # contagem + página (filme e autor via JOIN)
            response = self.client.get("/api/feed/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.data["results"]], [nova.id, antiga.id])
        first = response.data["results"][1]
        self.assertEqual(first["movie"]["tmdb_id"], 1)
        self.assertEqual(first["movie"]["title"], "Um")
        self.assertEqual(first["movie"]["poster_path"], "/1.jpg")
        self.assertEqual(first["author"]["username"], "amigo")

    def test_feed_vazio_sem_seguir_ninguem(self):
        self.client.force_authenticate(self.estranho)
        self.assertEqual(self.client.get("/api/feed/").data["results"], [])


class ResenhasDoUsuarioTests(APITestCase):
    def test_lista_resenhas_ativas_do_usuario(self):
        user = criar_usuario("autor")
        movie = Movie.objects.create(provider_movie_id=1, title="Um")
        outro = Movie.objects.create(provider_movie_id=2, title="Dois")
        ativa = Review.objects.create(user=user, movie=movie, content="a")
        Review.objects.create(user=user, movie=outro, content="b", is_active=False)
        Review.objects.create(user=criar_usuario("x"), movie=movie, content="c")

        response = self.client.get(f"/api/users/{user.id}/reviews/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.data["results"]], [ativa.id])

    def test_usuario_inexistente(self):
        self.assertEqual(self.client.get("/api/users/9999/reviews/").status_code, 404)


class BuscaDeUsuariosTests(APITestCase):
    def setUp(self):
        criar_usuario("maria", first_name="Maria", last_name="Silva")
        criar_usuario("joao", first_name="João", last_name="Marinho")
        criar_usuario("inativo", is_active=False)

    def test_busca_por_username_ou_nome_sem_email(self):
        response = self.client.get("/api/users/search/", {"q": "mari"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([u["username"] for u in response.data["results"]], ["joao", "maria"])
        self.assertEqual(
            set(response.data["results"][0]),
            {"id", "username", "first_name", "last_name", "avatar_url", "bio"},
        )

    def test_minimo_de_dois_caracteres(self):
        self.assertEqual(self.client.get("/api/users/search/", {"q": "m"}).status_code, 400)
        self.assertEqual(self.client.get("/api/users/search/").status_code, 400)

    def test_ignora_inativos(self):
        self.assertEqual(self.client.get("/api/users/search/", {"q": "inativo"}).data["count"], 0)
