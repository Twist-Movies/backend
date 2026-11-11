"""Cookie HttpOnly que carrega o refresh token (fora do alcance do JavaScript)."""
from django.conf import settings

CLIENT_HEADER = "HTTP_X_TWIST_CLIENT"
CLIENT_HEADER_VALUE = "web"


def set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        str(refresh_token),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        path=settings.REFRESH_COOKIE_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )
    return response


def clear_refresh_cookie(response):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        "",
        max_age=0,
        expires="Thu, 01 Jan 1970 00:00:00 GMT",
        path=settings.REFRESH_COOKIE_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )
    return response


def has_web_client_header(request):
    return request.META.get(CLIENT_HEADER) == CLIENT_HEADER_VALUE


def read_refresh_token(request):
    """Retorna (token, veio_do_cookie). O corpo (clientes não-navegador) tem prioridade."""
    body_token = request.data.get("refresh") if hasattr(request.data, "get") else None
    if body_token:
        return body_token, False
    cookie_token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
    if cookie_token:
        return cookie_token, True
    return None, False
