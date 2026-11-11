"""
Testes da recuperação de senha (RF01.06):

    POST /api/accounts/password-reset/
    POST /api/accounts/password-reset/confirm/

Executar com:
    DJANGO_SETTINGS_MODULE=config.settings.testing python manage.py test teste.test_password_reset
"""
import re
from unittest.mock import MagicMock, patch

import httpx
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache, caches
from django.core.mail import EmailMessage
from django.test import SimpleTestCase, override_settings
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.email import BrevoEmailBackend, EmailDeliveryError, ResendEmailBackend

User = get_user_model()

REQUEST_URL = "/api/accounts/password-reset/"
CONFIRM_URL = "/api/accounts/password-reset/confirm/"
LOGIN_URL = "/api/accounts/login/"
REFRESH_URL = "/api/accounts/token/refresh/"

OLD_PASSWORD = "Tw1st!Senha#Forte"
NEW_PASSWORD = "N0va!Senha#Segura9"
LINK_INVALIDO = "Link inválido ou expirado."


class PasswordResetBase(APITestCase):
    def setUp(self):
        cache.clear()
        caches["ratelimit"].clear()
        self.user = User.objects.create_user(
            username="maria", email="maria@example.com", password=OLD_PASSWORD,
            birth_date="2000-01-15",
        )

    def tearDown(self):
        cache.clear()
        caches["ratelimit"].clear()

    def _uid_token(self, user=None):
        user = user or self.user
        return urlsafe_base64_encode(str(user.pk).encode()), default_token_generator.make_token(user)

    def _confirm(self, uid, token, password=NEW_PASSWORD):
        return self.client.post(
            CONFIRM_URL, {"uid": uid, "token": token, "new_password": password}, format="json"
        )

    def _login(self, password):
        return self.client.post(LOGIN_URL, {"identifier": "maria", "password": password}, format="json")

    def _throttle_rates(self, scope, rate):
        rates = {**ScopedRateThrottle.THROTTLE_RATES, scope: rate}
        return patch.object(ScopedRateThrottle, "THROTTLE_RATES", rates)


class PasswordResetRequestTests(PasswordResetBase):
    def test_email_existente_envia_um_email_com_link(self):
        response = self.client.post(REQUEST_URL, {"email": "maria@example.com"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["maria@example.com"])
        uid, _ = self._uid_token()
        self.assertIn(f"http://frontend.test/redefinir-senha/{uid}/", email.body)
        self.assertIn("60 minutos", email.body)

    def test_email_inexistente_retorna_mesmo_corpo_sem_enviar(self):
        ok = self.client.post(REQUEST_URL, {"email": "maria@example.com"}, format="json")
        mail.outbox.clear()
        cache.clear()
        caches["ratelimit"].clear()

        nope = self.client.post(REQUEST_URL, {"email": "naoexiste@example.com"}, format="json")

        self.assertEqual(nope.status_code, status.HTTP_200_OK)
        self.assertEqual(nope.data, ok.data)
        self.assertEqual(mail.outbox, [])

    def test_usuario_inativo_nao_recebe_email(self):
        self.user.is_active = False
        self.user.save()

        response = self.client.post(REQUEST_URL, {"email": "maria@example.com"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mail.outbox, [])

    def test_email_invalido_retorna_400(self):
        response = self.client.post(REQUEST_URL, {"email": "isso-nao-e-email"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertEqual(mail.outbox, [])

    def test_falha_no_envio_ainda_retorna_200(self):
        with patch("apps.accounts.services.send_mail", side_effect=EmailDeliveryError("boom")):
            with self.assertLogs("apps.accounts.services", level="ERROR"):
                response = self.client.post(REQUEST_URL, {"email": "maria@example.com"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_limite_por_email_nao_revela_nada(self):
        for _ in range(5):
            response = self.client.post(REQUEST_URL, {"email": "maria@example.com"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(mail.outbox), 3)

    def test_throttle_retorna_429(self):
        with self._throttle_rates("password_reset_request", "2/hour"):
            codes = [
                self.client.post(REQUEST_URL, {"email": "x@example.com"}, format="json").status_code
                for _ in range(3)
            ]

        self.assertEqual(codes, [200, 200, 429])

    def test_throttle_nao_afeta_login(self):
        with self._throttle_rates("password_reset_request", "1/hour"):
            self.client.post(REQUEST_URL, {"email": "x@example.com"}, format="json")
            self.client.post(REQUEST_URL, {"email": "x@example.com"}, format="json")
            for _ in range(3):
                self.assertEqual(self._login(OLD_PASSWORD).status_code, status.HTTP_200_OK)


class PasswordResetConfirmTests(PasswordResetBase):
    def test_confirmar_troca_a_senha(self):
        uid, token = self._uid_token()

        response = self._confirm(uid, token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._login(NEW_PASSWORD).status_code, status.HTTP_200_OK)
        self.assertEqual(self._login(OLD_PASSWORD).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_nao_pode_ser_reutilizado(self):
        uid, token = self._uid_token()
        self._confirm(uid, token)

        response = self._confirm(uid, token, password="Out7a!Senha#Segura2")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], LINK_INVALIDO)
        self.assertEqual(self._login(NEW_PASSWORD).status_code, status.HTTP_200_OK)

    def test_token_adulterado(self):
        uid, token = self._uid_token()

        response = self._confirm(uid, token[:-1] + ("a" if token[-1] != "a" else "b"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], LINK_INVALIDO)
        self.assertEqual(self._login(OLD_PASSWORD).status_code, status.HTTP_200_OK)

    def test_uid_invalido(self):
        _, token = self._uid_token()
        outro_uid = urlsafe_base64_encode(b"999999")

        for uid in ("###", "abc", outro_uid):
            response = self._confirm(uid, token)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data["detail"], LINK_INVALIDO)

    def test_campos_ausentes_retornam_400_generico(self):
        response = self.client.post(CONFIRM_URL, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], LINK_INVALIDO)

    def test_token_expirado(self):
        uid, token = self._uid_token()

        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            response = self._confirm(uid, token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], LINK_INVALIDO)

    def test_usuario_inativo_nao_redefine(self):
        uid, token = self._uid_token()
        self.user.is_active = False
        self.user.save()

        self.assertEqual(self._confirm(uid, token).status_code, status.HTTP_400_BAD_REQUEST)

    def test_senha_fraca_mantem_token_valido(self):
        uid, token = self._uid_token()

        fraca = self._confirm(uid, token, password="123")

        self.assertEqual(fraca.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", fraca.data)
        self.assertEqual(self._login(OLD_PASSWORD).status_code, status.HTTP_200_OK)
        self.assertEqual(self._confirm(uid, token).status_code, status.HTTP_200_OK)

    def test_refresh_antigo_e_invalidado(self):
        refresh = str(RefreshToken.for_user(self.user))
        uid, token = self._uid_token()
        antes = self.client.post(REFRESH_URL, {"refresh": refresh}, format="json")
        self.assertEqual(antes.status_code, status.HTTP_200_OK)

        self._confirm(uid, token)

        depois = self.client.post(REFRESH_URL, {"refresh": refresh}, format="json")
        self.assertEqual(depois.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_throttle_retorna_429(self):
        with self._throttle_rates("password_reset_confirm", "2/hour"):
            codes = [self._confirm("abc", "x").status_code for _ in range(3)]

        self.assertEqual(codes, [400, 400, 429])


class PasswordResetFluxoCompletoTests(PasswordResetBase):
    def test_solicita_le_link_da_outbox_confirma_e_loga(self):
        self.client.post(REQUEST_URL, {"email": "maria@example.com"}, format="json")
        self.assertEqual(len(mail.outbox), 1)

        match = re.search(r"/redefinir-senha/([^/\s]+)/([^/\s]+)", mail.outbox[0].body)
        self.assertIsNotNone(match)
        uid, token = match.groups()

        self.assertEqual(self._confirm(uid, token).status_code, status.HTTP_200_OK)

        login = self._login(NEW_PASSWORD)
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertIn("access", login.data)


class ResendEmailBackendTests(SimpleTestCase):
    def _message(self):
        return EmailMessage("Assunto", "Corpo", "Twist <onboarding@resend.dev>", ["a@example.com"])

    @override_settings(RESEND_API_KEY="chave-de-teste")
    @patch("apps.common.email.httpx.post")
    def test_envia_para_api_do_resend(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text="{}")

        enviados = ResendEmailBackend().send_messages([self._message()])

        self.assertEqual(enviados, 1)
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.resend.com/emails")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer chave-de-teste")
        self.assertEqual(
            kwargs["json"],
            {"from": "Twist <onboarding@resend.dev>", "to": ["a@example.com"],
             "subject": "Assunto", "text": "Corpo"},
        )
        self.assertIn("timeout", kwargs)

    @override_settings(RESEND_API_KEY="chave-de-teste")
    @patch("apps.common.email.httpx.post")
    def test_erro_http_levanta_excecao_clara(self, mock_post):
        mock_post.return_value = MagicMock(status_code=403, text="forbidden")

        with self.assertLogs("apps.common.email", level="ERROR"):
            with self.assertRaises(EmailDeliveryError):
                ResendEmailBackend().send_messages([self._message()])

    @override_settings(RESEND_API_KEY="chave-de-teste")
    @patch("apps.common.email.httpx.post", side_effect=httpx.ConnectError("sem rede"))
    def test_fail_silently_engole_erro(self, mock_post):
        with self.assertLogs("apps.common.email", level="ERROR"):
            enviados = ResendEmailBackend(fail_silently=True).send_messages([self._message()])

        self.assertEqual(enviados, 0)

    @override_settings(RESEND_API_KEY="")
    @patch("apps.common.email.httpx.post")
    def test_sem_chave_nao_chama_a_rede(self, mock_post):
        with self.assertLogs("apps.common.email", level="ERROR"):
            with self.assertRaises(EmailDeliveryError):
                ResendEmailBackend().send_messages([self._message()])

        mock_post.assert_not_called()


class BrevoEmailBackendTests(SimpleTestCase):
    def _message(self):
        return EmailMessage("Assunto", "Corpo", "Twist <twist@example.com>", ["a@example.com"])

    @override_settings(BREVO_API_KEY="chave-de-teste")
    @patch("apps.common.email.httpx.post")
    def test_envia_para_api_do_brevo(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201, text="{}")

        enviados = BrevoEmailBackend().send_messages([self._message()])

        self.assertEqual(enviados, 1)
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(kwargs["headers"]["api-key"], "chave-de-teste")
        self.assertEqual(
            kwargs["json"],
            {"sender": {"email": "twist@example.com", "name": "Twist"},
             "to": [{"email": "a@example.com"}],
             "subject": "Assunto", "textContent": "Corpo"},
        )
        self.assertIn("timeout", kwargs)

    @override_settings(BREVO_API_KEY="chave-de-teste")
    @patch("apps.common.email.httpx.post")
    def test_remetente_sem_nome(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201, text="{}")
        mensagem = EmailMessage("A", "B", "twist@example.com", ["a@example.com"])

        BrevoEmailBackend().send_messages([mensagem])

        self.assertEqual(mock_post.call_args.kwargs["json"]["sender"], {"email": "twist@example.com"})

    @override_settings(BREVO_API_KEY="chave-de-teste")
    @patch("apps.common.email.httpx.post")
    def test_erro_http_levanta_excecao_clara(self, mock_post):
        mock_post.return_value = MagicMock(status_code=401, text="unauthorized")

        with self.assertLogs("apps.common.email", level="ERROR"):
            with self.assertRaises(EmailDeliveryError):
                BrevoEmailBackend().send_messages([self._message()])

    @override_settings(BREVO_API_KEY="chave-de-teste")
    @patch("apps.common.email.httpx.post", side_effect=httpx.ConnectError("sem rede"))
    def test_fail_silently_engole_erro(self, mock_post):
        with self.assertLogs("apps.common.email", level="ERROR"):
            enviados = BrevoEmailBackend(fail_silently=True).send_messages([self._message()])

        self.assertEqual(enviados, 0)

    @override_settings(BREVO_API_KEY="")
    @patch("apps.common.email.httpx.post")
    def test_sem_chave_nao_chama_a_rede(self, mock_post):
        with self.assertLogs("apps.common.email", level="ERROR"):
            with self.assertRaises(EmailDeliveryError):
                BrevoEmailBackend().send_messages([self._message()])

        mock_post.assert_not_called()
