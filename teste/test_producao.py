"""Endurecimento para produção: settings, healthz, docs, e-mail/exclusão com senha, TMDB, uploads."""
import importlib
import io
import os
import sys
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache, caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import clear_url_caches, reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common import images, storage
from apps.movies import tmdb
from apps.movies.models import Movie
from apps.movies.services import sync_movie
from teste.helpers import STRONG_PASSWORD, criar_usuario, tmdb_movie_payload

User = get_user_model()

LOGIN_URL = "/api/accounts/login/"
LOGOUT_URL = "/api/accounts/logout/"
REFRESH_URL = "/api/accounts/token/refresh/"
RESET_URL = "/api/accounts/password-reset/"
REGISTER_URL = "/api/accounts/register/"
ME_URL = "/api/users/me/"
COOKIE = "twist_refresh"


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        caches["ratelimit"].clear()


class SettingsProducaoTests(TestCase):
    def _carregar(self, **env):
        base = {"DATABASE_URL": "sqlite:///tmp.sqlite3", "SECRET_KEY": "x" * 60}
        env = {**base, **env}
        sys.modules.pop("config.settings.production", None)
        with patch.dict(os.environ, env):
            for k in ("CORS_ALLOWED_ORIGINS", "RENDER_EXTERNAL_HOSTNAME", "REFRESH_COOKIE_SAMESITE"):
                if k not in env:
                    os.environ.pop(k, None)
            return importlib.import_module("config.settings.production")

    def tearDown(self):
        sys.modules.pop("config.settings.production", None)

    def test_defaults_de_seguranca(self):
        prod = self._carregar(RENDER_EXTERNAL_HOSTNAME="twist-api.onrender.com")

        self.assertEqual(prod.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertTrue(prod.SECURE_SSL_REDIRECT)
        self.assertEqual(prod.SECURE_HSTS_SECONDS, 3600)
        self.assertFalse(prod.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertFalse(prod.SECURE_HSTS_PRELOAD)
        self.assertTrue(prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE)
        self.assertTrue(prod.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(prod.SECURE_REFERRER_POLICY, "same-origin")
        self.assertIn("https://twist-api.onrender.com", prod.CSRF_TRUSTED_ORIGINS)
        self.assertEqual(prod.SECURE_REDIRECT_EXEMPT, [r"^healthz/?$"])
        self.assertFalse(prod.DEBUG)
        self.assertFalse(prod.ENABLE_DOCS)

    def test_cookie_e_cors_de_producao(self):
        prod = self._carregar()

        self.assertEqual(prod.REFRESH_COOKIE_SAMESITE, "None")
        self.assertTrue(prod.REFRESH_COOKIE_SECURE)
        self.assertEqual(prod.CORS_ALLOWED_ORIGINS, ["https://twist-frontend.onrender.com"])

    def test_cors_e_samesite_configuraveis_por_env(self):
        prod = self._carregar(
            CORS_ALLOWED_ORIGINS="https://a.example,https://b.example", REFRESH_COOKIE_SAMESITE="Lax"
        )

        self.assertEqual(prod.CORS_ALLOWED_ORIGINS, ["https://a.example", "https://b.example"])
        self.assertEqual(prod.REFRESH_COOKIE_SAMESITE, "Lax")

    def test_wsgi_e_asgi_usam_producao_por_padrao(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for nome in ("wsgi.py", "asgi.py"):
            with open(os.path.join(base, "config", nome), encoding="utf-8") as f:
                self.assertIn("'config.settings.production'", f.read())

    def test_base_usa_localhost_e_caches_limitados(self):
        base = importlib.import_module("config.settings.base")

        self.assertEqual(base.CACHES["ratelimit"]["OPTIONS"], {"MAX_ENTRIES": 200000, "CULL_FREQUENCY": 4})
        self.assertEqual(base.CACHES["default"]["OPTIONS"], {"MAX_ENTRIES": 5000})
        self.assertEqual(base.CORS_ALLOWED_ORIGINS, ["http://localhost:5173"])


class HealthzTests(TestCase):
    def test_healthz_ok_sem_banco(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/healthz/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(len(ctx.captured_queries), 0)


class DocsEAdminTests(TestCase):
    def _recarregar(self):
        clear_url_caches()
        import config.urls

        importlib.reload(config.urls)

    def tearDown(self):
        clear_url_caches()
        import config.urls

        importlib.reload(config.urls)

    def test_docs_ativos_quando_habilitados(self):
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)

    @override_settings(ENABLE_DOCS=False, DEBUG=False)
    def test_docs_ocultos_por_padrao(self):
        self._recarregar()

        for url in ("/api/docs/", "/api/schema/", "/api/redoc/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    @override_settings(ENABLE_DOCS=False, DEBUG=True)
    def test_docs_ativos_com_debug(self):
        self._recarregar()

        self.assertEqual(self.client.get("/api/schema/").status_code, 200)

    @override_settings(ADMIN_URL="painel-secreto/")
    def test_admin_em_url_configuravel(self):
        self._recarregar()

        self.assertEqual(self.client.get("/admin/login/").status_code, 404)
        self.assertEqual(self.client.get("/painel-secreto/login/").status_code, 200)


class TrocaDeEmailTests(Base):
    def setUp(self):
        super().setUp()
        self.user = criar_usuario("ana", email="ana@example.com")
        self.client.force_authenticate(self.user)

    def _login_real(self):
        self.client.force_authenticate(None)
        return self.client.post(LOGIN_URL, {"identifier": "ana", "password": STRONG_PASSWORD}, format="json")

    def test_trocar_email_sem_senha_400(self):
        response = self.client.patch(ME_URL, {"email": "novo@example.com"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("senha atual", response.data["current_password"][0])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ana@example.com")

    def test_trocar_email_com_senha_errada_400(self):
        response = self.client.patch(
            ME_URL, {"email": "novo@example.com", "current_password": "errada"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("incorreta", response.data["current_password"][0])

    def test_trocar_email_ok_revoga_refresh_apaga_cookie_e_avisa_email_antigo(self):
        refresh = str(RefreshToken.for_user(self.user))

        response = self.client.patch(
            ME_URL, {"email": "Novo@Example.com", "current_password": STRONG_PASSWORD}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "novo@example.com")
        depois = self.client.post(REFRESH_URL, {"refresh": refresh}, format="json")
        self.assertEqual(depois.status_code, 401)
        self.assertEqual(mail.outbox[-1].to, ["ana@example.com"])

    def test_alterar_so_nome_e_bio_nao_pede_senha_nem_revoga(self):
        refresh = str(RefreshToken.for_user(self.user))

        response = self.client.patch(ME_URL, {"first_name": "Ana", "bio": "oi"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(COOKIE, response.cookies)
        self.assertEqual(self.client.post(REFRESH_URL, {"refresh": refresh}, format="json").status_code, 200)

    def test_reenviar_o_mesmo_email_nao_exige_senha(self):
        response = self.client.patch(ME_URL, {"email": "ANA@example.com"}, format="json")

        self.assertEqual(response.status_code, 200)


class ExclusaoDeContaTests(Base):
    def setUp(self):
        super().setUp()
        self.user = criar_usuario("ana")
        self.client.force_authenticate(self.user)

    def test_exige_senha(self):
        for corpo in ({"username": "ana"}, {"username": "ana", "password": "errada"}):
            response = self.client.delete(ME_URL, corpo, format="json")
            self.assertEqual(response.status_code, 400, corpo)
        self.assertTrue(User.objects.filter(username="ana").exists())

    def test_exige_username(self):
        response = self.client.delete(ME_URL, {"password": STRONG_PASSWORD}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_exclui_com_username_e_senha_e_apaga_cookie(self):
        response = self.client.delete(
            ME_URL, {"username": "ana", "password": STRONG_PASSWORD}, format="json"
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)
        self.assertFalse(User.objects.filter(username="ana").exists())


class TmdbErrosGenericosTests(Base):
    def test_503_nao_vaza_detalhe(self):
        with patch("apps.movies.views.tmdb.get_movie", side_effect=tmdb.TMDBError("chave abc123 inválida")):
            response = self.client.get("/api/movies/550/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {"error": "Serviço de filmes indisponível no momento."})

    def test_404_generico(self):
        with patch("apps.movies.views.tmdb.get_movie", side_effect=tmdb.TMDBNotFound("interno")):
            response = self.client.get("/api/movies/550/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, {"error": "Filme não encontrado."})

    def test_detalhe_fica_no_log(self):
        with patch("apps.movies.views.tmdb.get_movie", side_effect=tmdb.TMDBError("detalhe-interno")):
            with self.assertLogs("apps.movies.views", level="WARNING") as logs:
                self.client.get("/api/movies/550/")

        self.assertIn("detalhe-interno", logs.output[0])


class LoginPorContaEIpTests(Base):
    @override_settings(LOGIN_FAILURE_LIMIT=3)
    def test_falhas_de_outro_ip_nao_trancam_a_conta(self):
        criar_usuario("maria")
        for _ in range(3):
            self.client.post(
                LOGIN_URL, {"identifier": "maria", "password": "errada"}, format="json",
                HTTP_X_FORWARDED_FOR="9.9.9.9",
            )

        bloqueado = self.client.post(
            LOGIN_URL, {"identifier": "maria", "password": STRONG_PASSWORD}, format="json",
            HTTP_X_FORWARDED_FOR="9.9.9.9",
        )
        outro_ip = self.client.post(
            LOGIN_URL, {"identifier": "maria", "password": STRONG_PASSWORD}, format="json",
            HTTP_X_FORWARDED_FOR="8.8.8.8",
        )

        self.assertEqual(bloqueado.status_code, 429)
        self.assertEqual(outro_ip.status_code, 200)


class ResetAssincronoTests(Base):
    def setUp(self):
        super().setUp()
        criar_usuario("maria", email="maria@example.com")

    @override_settings(PASSWORD_RESET_EMAIL_ASYNC=True)
    def test_envio_em_thread_daemon(self):
        with patch("apps.accounts.services.threading.Thread") as thread:
            response = self.client.post(RESET_URL, {"email": "maria@example.com"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()
        self.assertEqual(len(mail.outbox), 0)  # nada enviado na requisição

    @override_settings(PASSWORD_RESET_EMAIL_ASYNC=True)
    def test_mesmo_caminho_para_email_inexistente(self):
        with patch("apps.accounts.services.threading.Thread") as thread:
            response = self.client.post(RESET_URL, {"email": "ninguem@example.com"}, format="json")

        self.assertEqual(response.status_code, 200)
        thread.return_value.start.assert_called_once()

    @override_settings(PASSWORD_RESET_EMAIL_ASYNC=True)
    def test_falha_na_thread_so_loga(self):
        with patch("apps.accounts.services.send_password_reset_email", side_effect=RuntimeError("boom")), \
                patch("apps.accounts.services.connections"), \
                patch("apps.accounts.services.threading.Thread") as thread:
            self.client.post(RESET_URL, {"email": "maria@example.com"}, format="json")
            alvo = thread.call_args.kwargs["target"]
            with self.assertLogs("apps.accounts.services", level="ERROR"):
                alvo(*thread.call_args.kwargs["args"])

    def test_sincrono_por_padrao_nos_testes(self):
        self.client.post(RESET_URL, {"email": "maria@example.com"}, format="json")

        self.assertEqual(len(mail.outbox), 1)


class SyncMovieSemEscritaTests(TestCase):
    def _escritas(self, ctx):
        return [q["sql"] for q in ctx.captured_queries if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]

    def test_cria_so_se_nao_existe_e_nao_reescreve_sem_mudancas(self):
        data = tmdb_movie_payload(550)
        sync_movie(data)

        with CaptureQueriesContext(connection) as ctx:
            sync_movie(data)
            sync_movie(tmdb_movie_payload(550, vote_average=8.456))  # 8.46 != 8.40: muda

        self.assertEqual(len(self._escritas(ctx)), 1)

    def test_get_detalhe_sem_mudancas_nao_escreve(self):
        data = tmdb_movie_payload(550, vote_average=8.4)
        sync_movie(data)

        with patch("apps.movies.views.tmdb.get_movie", return_value=data), CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/api/movies/550/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._escritas(ctx), [])

    def test_atualiza_quando_mudou(self):
        sync_movie(tmdb_movie_payload(550, title="Antigo"))

        sync_movie(tmdb_movie_payload(550, title="Novo"))

        self.assertEqual(Movie.objects.get(provider_movie_id=550).title, "Novo")
        self.assertEqual(Movie.objects.count(), 1)


def _imagem(formato="PNG", tamanho=(8, 8), nome="a", mode="RGB", exif=None):
    buffer = io.BytesIO()
    imagem = Image.new(mode, tamanho, "red")
    kwargs = {"exif": exif} if exif else {}
    imagem.save(buffer, format=formato, **kwargs)
    return buffer.getvalue()


class UploadDeImagemTests(Base):
    def _register(self, arquivo):
        return self.client.post(REGISTER_URL, {
            "username": "foto", "email": "foto@example.com", "password": STRONG_PASSWORD,
            "birth_date": "2000-01-01", "avatar": arquivo,
        }, format="multipart")

    def _supabase_mock(self):
        mock = MagicMock()
        mock.storage.from_.return_value.get_public_url.return_value = "https://cdn.test/x"
        return mock

    def test_reencoda_com_formato_e_content_type_reais(self):
        # arquivo JPEG real declarado como PNG pelo cliente
        arquivo = SimpleUploadedFile("a.png", _imagem("JPEG"), content_type="image/png")
        mock = self._supabase_mock()

        with patch.object(storage, "_supabase", mock):
            response = self._register(arquivo)

        self.assertEqual(response.status_code, 201, response.content)
        caminho, dados, opcoes = mock.storage.from_.return_value.upload.call_args.args
        self.assertTrue(caminho.endswith(".jpg"))
        self.assertEqual(opcoes["content-type"], "image/jpeg")
        self.assertEqual(Image.open(io.BytesIO(dados)).format, "JPEG")

    def test_remove_exif_e_aplica_rotacao(self):
        exif = Image.Exif()
        exif[274] = 6  # Orientation: rotaciona 90 graus
        exif[270] = "segredo-gps"
        arquivo = SimpleUploadedFile("a.jpg", _imagem("JPEG", (20, 10), exif=exif.tobytes()), content_type="image/jpeg")
        mock = self._supabase_mock()

        with patch.object(storage, "_supabase", mock):
            self._register(arquivo)

        dados = mock.storage.from_.return_value.upload.call_args.args[1]
        saida = Image.open(io.BytesIO(dados))
        self.assertEqual(saida.size, (10, 20))  # girou
        self.assertEqual(len(saida.getexif()), 0)
        self.assertNotIn(b"segredo-gps", dados)

    def test_aceita_webp(self):
        arquivo = SimpleUploadedFile("a.webp", _imagem("WEBP"), content_type="image/webp")
        mock = self._supabase_mock()

        with patch.object(storage, "_supabase", mock):
            response = self._register(arquivo)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(mock.storage.from_.return_value.upload.call_args.args[2]["content-type"], "image/webp")

    def test_rejeita_formato_real_nao_permitido(self):
        arquivo = SimpleUploadedFile("a.png", _imagem("GIF"), content_type="image/png")

        response = self._register(arquivo)

        self.assertEqual(response.status_code, 400)
        self.assertIn("avatar", response.data)

    def test_rejeita_conteudo_que_nao_e_imagem(self):
        arquivo = SimpleUploadedFile("a.png", b"<svg onload=alert(1)>", content_type="image/png")

        self.assertEqual(self._register(arquivo).status_code, 400)

    def test_rejeita_dimensoes_acima_de_4096(self):
        arquivo = SimpleUploadedFile("a.png", _imagem("PNG", (4097, 10)), content_type="image/png")

        response = self._register(arquivo)

        self.assertEqual(response.status_code, 400)
        self.assertIn("4096", str(response.data["avatar"]))

    def test_decompression_bomb_vira_400(self):
        arquivo = SimpleUploadedFile("a.png", _imagem("PNG", (100, 100)), content_type="image/png")

        with patch.object(images.Image, "MAX_IMAGE_PIXELS", 100):
            response = self._register(arquivo)

        self.assertEqual(response.status_code, 400)

    def test_falha_do_supabase_retorna_503(self):
        arquivo = SimpleUploadedFile("a.png", _imagem("PNG"), content_type="image/png")
        mock = self._supabase_mock()
        mock.storage.from_.return_value.upload.side_effect = RuntimeError("supabase caiu")

        with patch.object(storage, "_supabase", mock):
            response = self._register(arquivo)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("supabase", str(response.data).lower())
        self.assertFalse(User.objects.filter(username="foto").exists())


class LogoutSemAccessTests(Base):
    def setUp(self):
        super().setUp()
        self.user = criar_usuario("ana")

    def test_cookie_invalido_ou_revogado_retorna_205_e_apaga_cookie(self):
        self.client.cookies[COOKIE] = "lixo"

        response = self.client.post(LOGOUT_URL, {}, format="json", HTTP_X_TWIST_CLIENT="web")

        self.assertEqual(response.status_code, 205)
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)

    def test_cookie_valido_sem_access_revoga(self):
        refresh = str(RefreshToken.for_user(self.user))
        self.client.cookies[COOKIE] = refresh

        response = self.client.post(LOGOUT_URL, {}, format="json", HTTP_X_TWIST_CLIENT="web")

        self.assertEqual(response.status_code, 205)
        self.client.cookies.clear()
        self.assertEqual(self.client.post(REFRESH_URL, {"refresh": refresh}, format="json").status_code, 401)

    def test_sem_refresh_algum_400_e_apaga_cookie(self):
        response = self.client.post(LOGOUT_URL, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)

    def test_corpo_invalido_continua_400(self):
        response = self.client.post(LOGOUT_URL, {"refresh": "lixo"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)
