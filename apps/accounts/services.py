from django.contrib.auth import get_user_model

from apps.common.storage import upload_image

User = get_user_model()

AVATAR_BUCKET = "avatars"

def register_user(
    username, email, password, birth_date=None,
    first_name='', last_name='', bio=None, avatar=None,
):
    avatar_url = upload_image(avatar, AVATAR_BUCKET) if avatar else None

    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        birth_date=birth_date,
        first_name=first_name,
        last_name=last_name,
        bio=bio,
        avatar_url=avatar_url,
    )


def _find_login_user(identifier):
    """Busca por e-mail e depois username, sem diferenciar caixa.

    Se houver duplicatas antigas que só diferem na caixa, prefere o match exato e,
    na falta dele, o primeiro.
    """
    for field in ("email", "username"):
        candidatos = User.objects.filter(**{f"{field}__iexact": identifier}).order_by("pk")
        user = candidatos.filter(**{field: identifier}).first() or candidatos.first()
        if user is not None:
            return user
    return None


def _login_failure_key(identifier, ip=""):
    """Falhas por conta + IP (um atacante em outro IP não tranca a conta da vítima)."""
    digest = hashlib.sha256(f"{identifier.strip().lower()}|{ip}".encode()).hexdigest()
    return f"loginfail:{digest}"


def login_locked_out(identifier, ip=""):
    """True se a conta (identifier) estourou o limite de falhas na janela."""
    return caches["ratelimit"].get(_login_failure_key(identifier, ip), 0) >= settings.LOGIN_FAILURE_LIMIT


def _register_login_failure(identifier, ip=""):
    cache = caches["ratelimit"]
    key = _login_failure_key(identifier, ip)
    cache.add(key, 0, settings.LOGIN_FAILURE_WINDOW)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, settings.LOGIN_FAILURE_WINDOW)


def login_user(identifier, password, ip=""):
    """Autentica; conta só as falhas por identifier e zera o contador no sucesso."""
    user = _find_login_user(identifier)
    if user is not None and user.check_password(password):
        caches["ratelimit"].delete(_login_failure_key(identifier, ip))
        return user
    _register_login_failure(identifier, ip)
    return None


def update_profile(user, validated_data):
    avatar = validated_data.pop('avatar', None)
    if avatar:
        validated_data['avatar_url'] = upload_image(avatar, AVATAR_BUCKET)

    for field, value in validated_data.items():
        setattr(user, field, value)

    user.save()
    return user

# ---------------------------------------------------------------------------
# Recuperação de senha
# ---------------------------------------------------------------------------
import hashlib
import logging
import threading

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import caches
from django.db import connections
from django.core.mail import send_mail
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

logger = logging.getLogger(__name__)

PASSWORD_RESET_EMAIL_LIMIT = 3          # e-mails por endereço...
PASSWORD_RESET_EMAIL_WINDOW = 60 * 60   # ...por hora


def build_password_reset_link(user):
    uid = urlsafe_base64_encode(str(user.pk).encode())
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_URL.rstrip('/')}/redefinir-senha/{uid}/{token}"


def send_password_reset_email(email):
    """Envia o link de redefinição se existir usuário ativo com esse e-mail.

    Nunca levanta exceção nem revela se o e-mail existe: falhas são só logadas.
    """
    email = email.strip()
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        return False

    # Limite extra por e-mail (além do throttle por IP), silencioso.
    key = f"pwreset:{email.lower()}"
    cache = caches["ratelimit"]
    cache.add(key, 0, PASSWORD_RESET_EMAIL_WINDOW)
    try:
        if cache.incr(key) > PASSWORD_RESET_EMAIL_LIMIT:
            return False
    except ValueError:
        pass

    link = build_password_reset_link(user)
    minutos = max(settings.PASSWORD_RESET_TIMEOUT // 60, 1)
    corpo = (
        f"Olá, {user.first_name or user.username}!\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta no Twist.\n"
        f"Para criar uma nova senha, acesse o link abaixo (válido por {minutos} minutos):\n\n"
        f"{link}\n\n"
        "Se você não fez esse pedido, ignore este e-mail: sua senha continua a mesma.\n\n"
        "Equipe Twist"
    )
    try:
        send_mail("Redefinição de senha - Twist", corpo, None, [user.email])
    except Exception:
        logger.exception("Falha ao enviar e-mail de redefinição de senha (user_id=%s)", user.pk)
        return False
    return True


def dispatch_password_reset_email(email):
    """Envia o e-mail de reset; em thread daemon se PASSWORD_RESET_EMAIL_ASYNC (mesmo
    caminho/tempo de resposta exista a conta ou não). Falhas só são logadas."""
    def run(close_connections):
        try:
            send_password_reset_email(email)
        except Exception:
            logger.exception("Falha no envio do e-mail de redefinição de senha")
        finally:
            if close_connections:  # a thread tem conexões próprias com o banco
                connections.close_all()

    if settings.PASSWORD_RESET_EMAIL_ASYNC:
        threading.Thread(target=run, args=(True,), daemon=True).start()
    else:
        run(False)


def notify_email_changed(old_email, new_email):
    """Avisa o e-mail antigo sobre a troca (falhas só são logadas)."""
    try:
        send_mail(
            "E-mail da conta alterado - Twist",
            f"O e-mail da sua conta no Twist foi alterado para {new_email}.\n\n"
            "Se não foi você, redefina sua senha imediatamente.\n\nEquipe Twist",
            None,
            [old_email],
        )
    except Exception:
        logger.exception("Falha ao avisar sobre a troca de e-mail")


def get_user_from_reset_link(uid, token):
    """Retorna o usuário se uid/token forem válidos, senão None."""
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=pk, is_active=True)
    except (TypeError, ValueError, OverflowError, UnicodeDecodeError, User.DoesNotExist):
        return None
    if not default_token_generator.check_token(user, token):
        return None
    return user


def revoke_all_refresh_tokens(user):
    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)


def reset_password(user, new_password):
    """Valida e troca a senha (levanta ValidationError se for fraca)."""
    validate_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_all_refresh_tokens(user)
