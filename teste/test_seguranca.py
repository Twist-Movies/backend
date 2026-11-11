"""Limites de requisição, usuário excluído no refresh, e-mail/username sem caixa e nomes reservados."""
import importlib
from io import StringIO
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.core.management import CommandError, call_command
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from apps.movies import tmdb
from teste.helpers import STRONG_PASSWORD, criar_usuario

User = get_user_model()

LOGIN_URL = "/api/accounts/login/"
REGISTER_URL = "/api/accounts/register/"
REFRESH_URL = "/api/accounts/token/refresh/"
RESET_URL = "/api/accounts/password-reset/"
ME_URL = "/api/users/me/"


def taxas(**rates):
    """Baixa taxas de throttle (o dict de taxas é compartilhado entre as classes)."""
    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, rates)


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        caches["ratelimit"].clear()

    def registrar(self, username="novo", email="novo@example.com", **extra):
        data = {
            "username": username, "email": email, "password": STRONG_PASSWORD,
            "birth_date": "2000-01-15", **extra,
        }
        return self.client.post(REGISTER_URL, data)

    def login(self, identifier, password=STRONG_PASSWORD):
        return self.client.post(LOGIN_URL, {"identifier": identifier, "password": password}, format="json")


class RefreshUsuarioExcluidoTests(Base):
    def test_refresh_de_usuario_excluido_retorna_401_e_apaga_cookie(self):
        user = criar_usuario("fantasma")
        refresh = str(RefreshToken.for_user(user))
        user.delete()

        response = self.client.post(REFRESH_URL, {"refresh": refresh}, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.cookies["twist_refresh"]["max-age"], 0)


class ThrottleTests(Base):
    def test_login_por_ip_429_com_retry_after(self):
        criar_usuario("maria")
        with taxas(login="2/min"):
            codes = [self.login("maria").status_code for _ in range(2)]
            response = self.login("maria")

        self.assertEqual(codes, [200, 200])
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", response)

    def test_register_por_ip_429(self):
        with taxas(register="2/hour"):
            codes = [self.registrar(f"user{i}", f"u{i}@example.com").status_code for i in range(3)]

        self.assertEqual(codes, [201, 201, 429])

    @override_settings(LOGIN_FAILURE_LIMIT=3)
    def test_login_bloqueia_conta_apos_falhas_mesmo_com_senha_certa(self):
        criar_usuario("maria")
        codes = [self.login("maria", "errada").status_code for _ in range(3)]

        bloqueado = self.login("maria")
        outra_caixa = self.login("MARIA")

        self.assertEqual(codes, [401, 401, 401])
        self.assertEqual(bloqueado.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", bloqueado)
        self.assertEqual(outra_caixa.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @override_settings(LOGIN_FAILURE_LIMIT=3)
    def test_sucesso_zera_falhas_e_outra_conta_nao_e_afetada(self):
        criar_usuario("maria")
        criar_usuario("joao")
        for _ in range(2):
            self.login("maria", "errada")
        self.assertEqual(self.login("maria").status_code, 200)
        for _ in range(2):
            self.login("maria", "errada")

        self.assertEqual(self.login("maria").status_code, 200)
        for _ in range(3):
            self.login("joao", "errada")
        self.assertEqual(self.login("maria").status_code, 200)

    def test_tmdb_429(self):
        with taxas(tmdb="2/min"), patch("apps.movies.tmdb.httpx.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"results": [], "page": 1, "total_pages": 1, "total_results": 0}
            codes = [self.client.get("/api/movies/trending/").status_code for _ in range(3)]
            outra_rota = self.client.get("/api/movies/search/?q=matrix")

        self.assertEqual(codes[2], status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertNotIn(429, codes[:2])
        self.assertEqual(outra_rota.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_limite_global_anonimo_e_por_usuario(self):
        with taxas(anon="2/min"):
            codes = [self.client.get("/api/playlists/official/").status_code for _ in range(3)]
        self.assertEqual(codes[2], status.HTTP_429_TOO_MANY_REQUESTS)

        caches["ratelimit"].clear()
        self.client.force_authenticate(criar_usuario("logada"))
        with taxas(user="2/min"):
            codes = [self.client.get(ME_URL).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_xff_forjado_nao_burla_limite(self):
        with taxas(password_reset_request="2/hour"):
            codes = [
                self.client.post(
                    RESET_URL, {"email": "x@example.com"}, format="json",
                    HTTP_X_FORWARDED_FOR=f"6.6.6.{i}, 9.9.9.9",
                ).status_code
                for i in range(3)
            ]

        self.assertEqual(codes, [200, 200, 429])

    def test_contadores_ficam_no_cache_ratelimit(self):
        with taxas(register="5/hour"):
            self.registrar()

        self.assertTrue(any("throttle_register" in k for k in caches["ratelimit"]._cache))
        self.assertFalse(any("throttle_register" in k for k in cache._cache))


class EmailUsernameSemCaixaTests(Base):
    def test_cadastro_normaliza_email_para_minusculas(self):
        response = self.registrar("caixa", "CaIxA@Example.COM")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(User.objects.get(username="caixa").email, "caixa@example.com")

    def test_cadastro_rejeita_email_duplicado_com_outra_caixa(self):
        criar_usuario("ana", email="ana@example.com")

        response = self.registrar("ana2", "ANA@example.com")

        self.assertEqual(response.status_code, 400)
        self.assertIn("e-mail", str(response.data["email"][0]))

    def test_cadastro_rejeita_username_duplicado_com_outra_caixa(self):
        criar_usuario("Ana")

        response = self.registrar("ANA", "outra@example.com")

        self.assertEqual(response.status_code, 400)
        self.assertIn("em uso", str(response.data["username"][0]))

    def test_create_user_e_save_normalizam_email(self):
        user = User.objects.create_user("x", "X@Y.COM", "senha")
        self.assertEqual(user.email, "x@y.com")
        user.email = "OUTRO@Y.COM"
        user.save()

        user.refresh_from_db()
        self.assertEqual(user.email, "outro@y.com")

    def test_patch_normaliza_e_valida_unicidade(self):
        criar_usuario("ana", email="ana@example.com")
        bia = criar_usuario("bia")
        self.client.force_authenticate(bia)

        conflito = self.client.patch(ME_URL, {"email": "ANA@example.com"}, format="json")
        ok = self.client.patch(ME_URL, {"email": "BIA.Nova@Example.com", "current_password": STRONG_PASSWORD}, format="json")
        mesmo = self.client.patch(ME_URL, {"username": "bia"}, format="json")

        self.assertEqual(conflito.status_code, 400)
        self.assertEqual(ok.status_code, 200, ok.content)
        bia.refresh_from_db()
        self.assertEqual(bia.email, "bia.nova@example.com")
        self.assertEqual(mesmo.status_code, 200)

    def test_login_por_email_e_username_sem_caixa(self):
        criar_usuario("Maria", email="maria@example.com")

        self.assertEqual(self.login("MARIA@Example.com").status_code, 200)
        self.assertEqual(self.login("maria").status_code, 200)
        self.assertEqual(self.login("MARIA").status_code, 200)

    def test_login_com_duplicatas_antigas_prefere_match_exato(self):
        criar_usuario("Joao", email="a@example.com")
        segundo = criar_usuario("joao", email="b@example.com")
        segundo.set_password("OutraSenha#123")
        segundo.save()

        resposta = self.login("joao", "OutraSenha#123")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["username"], "joao")
        self.assertEqual(self.login("JOAO").status_code, 200)  # sem exato: o primeiro

    def test_migracao_de_dados_pula_conflitos(self):
        mod = importlib.import_module("apps.accounts.migrations.0002_normalize_emails")
        a = User.objects.create_user("a", "x@example.com", "s")
        b = User.objects.create_user("b", "y@example.com", "s")
        c = User.objects.create_user("c", "z@example.com", "s")
        User.objects.filter(pk=a.pk).update(email="X@example.com")
        User.objects.filter(pk=b.pk).update(email="Y@example.com")
        User.objects.filter(pk=c.pk).update(email="y@example.com")  # conflita com b
        with self.assertLogs("apps.accounts.migrations.0002_normalize_emails", level="WARNING"):
            mod.lowercase_emails(django_apps, None)

        self.assertEqual(User.objects.get(pk=a.pk).email, "x@example.com")
        self.assertEqual(User.objects.get(pk=b.pk).email, "Y@example.com")


class UsernamesReservadosTests(Base):
    def test_cadastro_bloqueia_reservados_sem_caixa(self):
        for nome in ("twist", "Admin", "ROOT", "Oficial", "undefined"):
            response = self.registrar(nome, f"{nome.lower()}@example.com")
            self.assertEqual(response.status_code, 400, nome)
            self.assertIn("reservado", str(response.data["username"][0]))

    def test_patch_bloqueia_reservado(self):
        self.client.force_authenticate(criar_usuario("carla"))

        response = self.client.patch(ME_URL, {"username": "Suporte"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("reservado", str(response.data["username"][0]))

    def test_conta_oficial_existente_pode_manter_o_proprio_username(self):
        oficial = criar_usuario("twist", is_staff=True)
        self.client.force_authenticate(oficial)

        response = self.client.patch(ME_URL, {"bio": "Conta oficial"}, format="json")

        self.assertEqual(response.status_code, 200)


class SeedContaOficialTests(Base):
    def _seed(self):
        with patch(
            "apps.movies.management.commands.seed_listas_oficiais.get_or_sync_movie",
            side_effect=tmdb.TMDBError("offline"),
        ):
            call_command("seed_listas_oficiais", stdout=StringIO())

    def test_aborta_se_twist_e_conta_comum_com_senha(self):
        criar_usuario("twist")

        with self.assertRaises(CommandError) as ctx:
            self._seed()

        self.assertIn("twist", str(ctx.exception))

    def test_aborta_se_twist_e_staff_mas_tem_senha_utilizavel(self):
        criar_usuario("twist", is_staff=True)

        with self.assertRaises(CommandError):
            self._seed()

    def test_aborta_se_twist_sem_senha_mas_nao_staff(self):
        user = criar_usuario("twist")
        user.set_unusable_password()
        user.save()

        with self.assertRaises(CommandError):
            self._seed()

    def test_aborta_se_existe_twist_com_outra_caixa(self):
        criar_usuario("Twist", is_staff=True)

        with self.assertRaises(CommandError):
            self._seed()

    def test_conta_criada_pelo_seed_pode_rodar_de_novo(self):
        self._seed()
        self._seed()

        oficial = User.objects.get(username="twist")
        self.assertTrue(oficial.is_staff)
        self.assertFalse(oficial.has_usable_password())
