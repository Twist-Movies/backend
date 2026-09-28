"""
Testes automatizados dos endpoints de autenticação já implementados:

    POST /api/accounts/register/
    POST /api/accounts/login/
    POST /api/accounts/token/refresh/
    POST /api/accounts/logout/

Executar com:
    DJANGO_SETTINGS_MODULE=config.settings.testing python manage.py test teste
"""
import io
import os
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def _gerar_imagem_png_valida():
    """Gera os bytes de um PNG 1x1 real, válido para o ImageField do serializer."""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


def _gerar_imagem_png_grande(largura=1600, altura=1600):
    """Gera um PNG válido, mas com ruído aleatório (incompressível) grande o
    suficiente para ultrapassar o limite de 5MB validado em
    `validate_avatar_file` (apps/accounts/serializers.py)."""
    dados_aleatorios = os.urandom(largura * altura * 3)
    imagem = Image.frombytes("RGB", (largura, altura), dados_aleatorios)
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()

REGISTER_URL = "/api/accounts/register/"
LOGIN_URL = "/api/accounts/login/"
LOGOUT_URL = "/api/accounts/logout/"
TOKEN_REFRESH_URL = "/api/accounts/token/refresh/"

# Senha "forte" o suficiente para passar pelos validadores padrão do Django
# (tamanho mínimo, não numérica, não comum, não muito parecida com o usuário).
STRONG_PASSWORD = "Tw1st!Senha#Forte"


class RegisterTests(APITestCase):
    def _payload(self, **overrides):
        data = {
            "username": "novousuario",
            "email": "novousuario@example.com",
            "password": STRONG_PASSWORD,
            "birth_date": "1995-05-20",
            "first_name": "Novo",
            "last_name": "Usuario",
        }
        data.update(overrides)
        return data

    @patch("apps.accounts.services.upload_avatar")
    def test_register_sucesso_cria_usuario(self, mock_upload_avatar):
        mock_upload_avatar.return_value = "https://dummy.storage/avatars/fake.png"

        avatar = SimpleUploadedFile(
            "avatar.png", _gerar_imagem_png_valida(), content_type="image/png"
        )
        payload = self._payload(avatar=avatar)

        response = self.client.post(REGISTER_URL, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(User.objects.filter(username="novousuario").exists())

        user = User.objects.get(username="novousuario")
        self.assertEqual(user.email, "novousuario@example.com")
        self.assertEqual(user.avatar_url, "https://dummy.storage/avatars/fake.png")
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        mock_upload_avatar.assert_called_once()

    def test_register_sucesso_sem_avatar(self):
        payload = self._payload()

        response = self.client.post(REGISTER_URL, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get(username="novousuario")
        self.assertIsNone(user.avatar_url)

    def test_register_falha_sem_campos_obrigatorios(self):
        # Faltando username, email, password e birth_date.
        response = self.client.post(REGISTER_URL, {}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        for field in ("username", "email", "password", "birth_date"):
            self.assertIn(field, response.data)
        self.assertFalse(User.objects.exists())

    def test_register_falha_username_duplicado(self):
        User.objects.create_user(
            username="novousuario",
            email="outro@example.com",
            password=STRONG_PASSWORD,
        )

        payload = self._payload(email="novousuario2@example.com")
        response = self.client.post(REGISTER_URL, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data)
        self.assertEqual(User.objects.count(), 1)

    def test_register_falha_email_duplicado(self):
        User.objects.create_user(
            username="usuarioexistente",
            email="novousuario@example.com",
            password=STRONG_PASSWORD,
        )

        payload = self._payload(username="outrousername")
        response = self.client.post(REGISTER_URL, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertEqual(User.objects.count(), 1)

    def test_register_falha_senha_fraca(self):
        # Puramente numérica e comum: reprovada pelo NumericPasswordValidator
        # e pelo CommonPasswordValidator do Django (usados via validate_password).
        payload = self._payload(password="12345678")

        response = self.client.post(REGISTER_URL, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(username="novousuario").exists())

    def test_register_falha_data_nascimento_futura(self):
        data_futura = (date.today() + timedelta(days=1)).isoformat()
        payload = self._payload(birth_date=data_futura)

        response = self.client.post(REGISTER_URL, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("birth_date", response.data)
        self.assertFalse(User.objects.filter(username="novousuario").exists())

    def test_register_falha_avatar_tipo_invalido(self):
        avatar = SimpleUploadedFile(
            "avatar.txt", b"isto nao e uma imagem", content_type="text/plain"
        )
        payload = self._payload(avatar=avatar)

        response = self.client.post(REGISTER_URL, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("avatar", response.data)
        self.assertFalse(User.objects.filter(username="novousuario").exists())

    def test_register_falha_avatar_maior_que_5mb(self):
        conteudo = _gerar_imagem_png_grande()
        self.assertGreater(len(conteudo), 5 * 1024 * 1024)  # garante que o teste testa o que promete

        avatar = SimpleUploadedFile("avatar.png", conteudo, content_type="image/png")
        payload = self._payload(avatar=avatar)

        response = self.client.post(REGISTER_URL, payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("avatar", response.data)
        self.assertFalse(User.objects.filter(username="novousuario").exists())


class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="usuarioteste",
            email="usuarioteste@example.com",
            password=STRONG_PASSWORD,
        )

    def test_login_sucesso_com_username(self):
        response = self.client.post(
            LOGIN_URL,
            {"identifier": "usuarioteste", "password": STRONG_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["username"], "usuarioteste")

    def test_login_sucesso_com_email(self):
        response = self.client.post(
            LOGIN_URL,
            {"identifier": "usuarioteste@example.com", "password": STRONG_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_falha_senha_errada(self):
        response = self.client.post(
            LOGIN_URL,
            {"identifier": "usuarioteste", "password": "senha-errada-123"},
            format="json",
        )

        # login_user() retorna None para senha errada e a view sempre
        # responde 401 nesse caso (ver apps/accounts/views.py::LoginView.post).
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data, {"error": "Invalid credentials"})

    def test_login_falha_usuario_inexistente(self):
        response = self.client.post(
            LOGIN_URL,
            {"identifier": "naoexiste", "password": STRONG_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data, {"error": "Invalid credentials"})

    def test_login_falha_campos_faltando(self):
        response = self.client.post(LOGIN_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("identifier", response.data)
        self.assertIn("password", response.data)


class TokenRefreshTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="usuarioteste",
            email="usuarioteste@example.com",
            password=STRONG_PASSWORD,
        )
        self.refresh = RefreshToken.for_user(self.user)

    def test_refresh_sucesso_retorna_novo_access(self):
        response = self.client.post(
            TOKEN_REFRESH_URL, {"refresh": str(self.refresh)}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data)
        self.assertTrue(response.data["access"])

    def test_refresh_falha_token_invalido(self):
        response = self.client.post(
            TOKEN_REFRESH_URL, {"refresh": "token-completamente-invalido"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_falha_sem_token(self):
        response = self.client.post(TOKEN_REFRESH_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LogoutTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="usuarioteste",
            email="usuarioteste@example.com",
            password=STRONG_PASSWORD,
        )

    def _autentica_e_gera_refresh(self):
        refresh = RefreshToken.for_user(self.user)
        access = refresh.access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return refresh

    def test_logout_sucesso_invalida_refresh_token(self):
        refresh = self._autentica_e_gera_refresh()

        response = self.client.post(
            LOGOUT_URL, {"refresh": str(refresh)}, format="json"
        )

        self.assertIn(
            response.status_code,
            (status.HTTP_200_OK, status.HTTP_205_RESET_CONTENT),
        )

        # O refresh token usado no logout deve ir para a blacklist e não
        # pode mais ser usado para gerar um novo access token.
        self.client.credentials()  # remove o header de autenticação
        refresh_response = self.client.post(
            TOKEN_REFRESH_URL, {"refresh": str(refresh)}, format="json"
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_falha_sem_autenticacao(self):
        refresh = RefreshToken.for_user(self.user)

        response = self.client.post(
            LOGOUT_URL, {"refresh": str(refresh)}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_falha_sem_refresh_no_body(self):
        self._autentica_e_gera_refresh()

        response = self.client.post(LOGOUT_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_falha_token_ja_revogado(self):
        refresh = self._autentica_e_gera_refresh()

        primeira_resposta = self.client.post(
            LOGOUT_URL, {"refresh": str(refresh)}, format="json"
        )
        self.assertIn(
            primeira_resposta.status_code,
            (status.HTTP_200_OK, status.HTTP_205_RESET_CONTENT),
        )

        segunda_resposta = self.client.post(
            LOGOUT_URL, {"refresh": str(refresh)}, format="json"
        )
        self.assertEqual(segunda_resposta.status_code, status.HTTP_400_BAD_REQUEST)
