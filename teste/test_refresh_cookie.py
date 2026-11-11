"""Refresh token em cookie HttpOnly (login, refresh, logout, reset de senha, exclusão, CORS)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

LOGIN_URL = "/api/accounts/login/"
LOGOUT_URL = "/api/accounts/logout/"
REFRESH_URL = "/api/accounts/token/refresh/"
CONFIRM_URL = "/api/accounts/password-reset/confirm/"
ME_URL = "/api/users/me/"
COOKIE = "twist_refresh"
WEB = {"HTTP_X_TWIST_CLIENT": "web"}
SENHA = "SenhaForte#2024"


class RefreshCookieBase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="cookieuser", email="cookie@example.com", password=SENHA
        )

    def login(self):
        return self.client.post(
            LOGIN_URL, {"identifier": "cookieuser", "password": SENHA}, format="json"
        )

    def assert_cookie_apagado(self, response):
        cookie = response.cookies[COOKIE]
        self.assertEqual(cookie.value, "")
        self.assertEqual(cookie["max-age"], 0)
        self.assertEqual(cookie["path"], "/api/accounts/")


class LoginCookieTests(RefreshCookieBase):
    def test_login_seta_cookie_httponly_sem_refresh_no_corpo(self):
        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), {"access", "username"})
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["path"], "/api/accounts/")
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["max-age"], 86400)
        self.assertEqual(cookie["secure"], "")  # testing.py: Secure=False

    @override_settings(REFRESH_COOKIE_SECURE=True, REFRESH_COOKIE_SAMESITE="None")
    def test_secure_e_samesite_respeitam_settings(self):
        cookie = self.login().cookies[COOKIE]

        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "None")

    @override_settings(REFRESH_COOKIE_NAME="outro_nome")
    def test_nome_do_cookie_configuravel(self):
        self.assertIn("outro_nome", self.login().cookies)


class RefreshViaCookieTests(RefreshCookieBase):
    def test_cookie_sem_header_retorna_403(self):
        self.login()  # o cliente de teste guarda o cookie

        response = self.client.post(REFRESH_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("error", response.data)

    def test_cookie_com_header_retorna_novo_access(self):
        self.login()

        response = self.client.post(REFRESH_URL, {}, format="json", **WEB)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), {"access"})
        self.assertTrue(response.data["access"])

    def test_fallback_refresh_no_corpo_sem_header(self):
        refresh = str(RefreshToken.for_user(self.user))

        response = self.client.post(REFRESH_URL, {"refresh": refresh}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_refresh_invalido_401_e_apaga_cookie(self):
        self.client.cookies[COOKIE] = "lixo"

        response = self.client.post(REFRESH_URL, {}, format="json", **WEB)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assert_cookie_apagado(response)

    def test_sem_refresh_algum_401(self):
        response = self.client.post(REFRESH_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assert_cookie_apagado(response)


class LogoutCookieTests(RefreshCookieBase):
    def _login_autenticado(self):
        access = self.login().data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def test_logout_via_cookie_revoga_e_apaga_cookie(self):
        self._login_autenticado()
        refresh = self.client.cookies[COOKIE].value

        response = self.client.post(LOGOUT_URL, {}, format="json", **WEB)

        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)
        self.assert_cookie_apagado(response)
        self.client.credentials()
        self.client.cookies.clear()
        depois = self.client.post(REFRESH_URL, {"refresh": refresh}, format="json")
        self.assertEqual(depois.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_via_cookie_sem_header_403(self):
        self._login_autenticado()

        response = self.client.post(LOGOUT_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_logout_via_corpo(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = self.client.post(LOGOUT_URL, {"refresh": str(refresh)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)
        self.assert_cookie_apagado(response)

    def test_logout_sem_token_400_mas_apaga_cookie(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}"
        )

        response = self.client.post(LOGOUT_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_cookie_apagado(response)

    def test_logout_token_ja_revogado_400_apaga_cookie(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        self.client.post(LOGOUT_URL, {"refresh": str(refresh)}, format="json")

        response = self.client.post(LOGOUT_URL, {"refresh": str(refresh)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_cookie_apagado(response)


class CookieEmOutrosFluxosTests(RefreshCookieBase):
    def test_reset_de_senha_apaga_cookie_e_invalida_refresh(self):
        self.login()
        refresh = self.client.cookies[COOKIE].value
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        response = self.client.post(
            CONFIRM_URL,
            {"uid": uid, "token": token, "new_password": "NovaSenha#2024"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assert_cookie_apagado(response)
        self.client.cookies.clear()
        depois = self.client.post(REFRESH_URL, {"refresh": refresh}, format="json")
        self.assertEqual(depois.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_exclusao_de_conta_apaga_cookie(self):
        access = self.login().data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = self.client.delete(ME_URL, {"username": "cookieuser", "password": SENHA}, format="json")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assert_cookie_apagado(response)


class CorsTests(APITestCase):
    def preflight(self, origin):
        return self.client.options(
            REFRESH_URL,
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type, x-twist-client",
        )

    def test_origem_permitida_aceita_header_e_credenciais(self):
        response = self.preflight("http://localhost:5173")

        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertEqual(response["Access-Control-Allow-Credentials"], "true")
        permitidos = response["Access-Control-Allow-Headers"].lower()
        self.assertIn("x-twist-client", permitidos)
        self.assertIn("authorization", permitidos)  # padrões preservados

    def test_origem_estranha_nao_recebe_cors(self):
        response = self.preflight("https://evil.example.com")

        self.assertNotIn("Access-Control-Allow-Origin", response)
        self.assertNotIn("Access-Control-Allow-Credentials", response)
