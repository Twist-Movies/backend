from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import generics
from rest_framework.permissions import AllowAny

from .serializers import PasswordResetRequestSerializer, PasswordResetConfirmSerializer, FollowerSerializer, FollowingSerializer, RegisterSerializer, LoginSerializer, UpdateProfileSerializer, UserSerializer
from .services import (
    register_user, login_user, login_locked_out, dispatch_password_reset_email,
    notify_email_changed, revoke_all_refresh_tokens, update_profile,
    get_user_from_reset_link, reset_password,
)
from rest_framework.exceptions import Throttled
from rest_framework.throttling import BaseThrottle
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework.parsers import MultiPartParser, FormParser

from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

from .cookies import (
    clear_refresh_cookie, has_web_client_header, read_refresh_token, set_refresh_cookie,
)

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.db import IntegrityError
from .models import Follow, User

CSRF_HEADER_ERROR = {"error": "Header 'X-Twist-Client: web' obrigatório quando o refresh vem do cookie."}


@extend_schema(
    tags=['Autenticação'],
    description=(
        "Revoga o refresh token (blacklist) e sempre apaga o cookie `twist_refresh`. "
        "Não exige access token válido. Cookie inválido/já revogado: 205 (cookie apagado); "
        "corpo inválido/já revogado ou nenhum refresh informado: 400 (cookie também apagado). "
        "O refresh vem do cookie HttpOnly (exige o header `X-Twist-Client: web`) ou, "
        "para clientes não-navegador, do campo `refresh` do corpo."
    ),
    request={'application/json': {'type': 'object', 'properties': {'refresh': {'type': 'string'}}}},
    responses={
        205: OpenApiResponse(description='Logout realizado — refresh token revogado e cookie apagado'),
        400: OpenApiResponse(description='Token ausente ou já revogado (o cookie também é apagado)'),
        403: OpenApiResponse(description="Refresh via cookie sem o header 'X-Twist-Client: web'"),
    },
)
class LogoutView(APIView):
    # Não exige access válido (ele pode ter expirado): a sessão é encerrada pelo refresh.
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh_token, from_cookie = read_refresh_token(request)
        if from_cookie and not has_web_client_header(request):
            return Response(CSRF_HEADER_ERROR, status=status.HTTP_403_FORBIDDEN)

        if not refresh_token:
            return clear_refresh_cookie(Response(
                {"error": "O campo 'refresh' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            ))

        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            if from_cookie:
                # Cookie inválido/já revogado: a sessão já não vale; só limpamos o cookie.
                return clear_refresh_cookie(Response(status=status.HTTP_205_RESET_CONTENT))
            return clear_refresh_cookie(Response(
                {"error": "Token inválido ou já revogado."},
                status=status.HTTP_400_BAD_REQUEST,
            ))

        return clear_refresh_cookie(Response(status=status.HTTP_205_RESET_CONTENT))


@extend_schema(
    tags=['Autenticação'],
    description=(
        "Gera um novo access token. O refresh vem do cookie HttpOnly `twist_refresh` "
        "(exige o header `X-Twist-Client: web`) ou, para clientes não-navegador, do campo "
        "`refresh` do corpo. Refresh inválido/ausente/revogado: 401 e o cookie é apagado."
    ),
    request={'application/json': {'type': 'object', 'properties': {'refresh': {'type': 'string'}}}},
    responses={
        200: OpenApiResponse(description='Novo access token: {"access": "<token>"}'),
        401: OpenApiResponse(description='Refresh ausente, inválido, expirado ou revogado'),
        403: OpenApiResponse(description="Refresh via cookie sem o header 'X-Twist-Client: web'"),
    },
)
class CookieTokenRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh_token, from_cookie = read_refresh_token(request)
        if from_cookie and not has_web_client_header(request):
            return Response(CSRF_HEADER_ERROR, status=status.HTTP_403_FORBIDDEN)

        serializer = TokenRefreshSerializer(data={"refresh": refresh_token or ""})
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:  # TokenError/InvalidToken/ValidationError: sessão inválida
            return clear_refresh_cookie(Response(
                {"error": "Refresh token ausente, inválido ou expirado."},
                status=status.HTTP_401_UNAUTHORIZED,
            ))

        return Response({"access": serializer.validated_data["access"]}, status=status.HTTP_200_OK)

@extend_schema(
    tags=['Autenticação'],
    request=RegisterSerializer,
    responses={
        201: OpenApiResponse(description='Usuário criado com sucesso'),
        400: OpenApiResponse(description='Erro de validação (e-mail/username duplicado ou reservado, senha fraca, etc.)'),
        429: OpenApiResponse(description='Muitos cadastros deste IP (Retry-After)'),
    },
)
class RegisterView(APIView):
    throttle_scope = 'register'
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = register_user(**serializer.validated_data)

        return Response(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "birth_date": user.birth_date,
                "bio": user.bio,
                "avatar_url": user.avatar_url,
            },
            status=status.HTTP_201_CREATED,
        )

@extend_schema(
    tags=['Autenticação'],
    request=LoginSerializer,
    responses={
        200: OpenApiResponse(description='Login bem-sucedido — retorna {access, username} e define o cookie HttpOnly `twist_refresh`'),
        401: OpenApiResponse(description='Credenciais inválidas'),
        429: OpenApiResponse(description='Limite por IP ou muitas falhas para a conta (Retry-After)'),
    },
)
class LoginView(APIView):
    throttle_scope = 'login'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ip = BaseThrottle().get_ident(request)
        if login_locked_out(serializer.validated_data['identifier'], ip):
            raise Throttled(wait=settings.LOGIN_FAILURE_WINDOW)

        user = login_user(**serializer.validated_data, ip=ip)
        if user is None:
            return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        response = Response(
            {"access": str(refresh.access_token), "username": user.username},
            status=status.HTTP_200_OK,
        )
        return set_refresh_cookie(response, refresh)

@extend_schema_view(
    get=extend_schema(tags=['Usuários'], responses=UserSerializer),
    patch=extend_schema(
        tags=['Usuários'],
        description="Atualiza o perfil. Alterar o `email` exige `current_password` correta; "
                    "a troca revoga todos os refresh tokens e apaga o cookie `twist_refresh`.",
        request=UpdateProfileSerializer,
        responses={
            200: UserSerializer,
            400: OpenApiResponse(description='Validação (e-mail/username duplicado ou reservado, senha atual ausente/incorreta)'),
        },
    ),
    delete=extend_schema(
        tags=['Usuários'],
        description="Exclui a conta. Exige `username` e `password` no corpo; apaga o cookie `twist_refresh`.",
        request={'application/json': {'type': 'object', 'properties': {
            'username': {'type': 'string'}, 'password': {'type': 'string'}}}},
        responses={204: OpenApiResponse(description='Conta excluída'),
                   400: OpenApiResponse(description='Username ou senha ausentes/incorretos')},
    ),
)
class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UpdateProfileSerializer(request.user, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        old_email = request.user.email
        user = update_profile(request.user, serializer.validated_data)
        response = Response(UserSerializer(user).data)
        if user.email != old_email:
            # Troca de e-mail encerra todas as sessões (refresh tokens) e limpa o cookie.
            revoke_all_refresh_tokens(user)
            notify_email_changed(old_email, user.email)
            clear_refresh_cookie(response)
        return response
    
    def delete(self, request):
        username_confirmation = request.data.get('username')

        if not username_confirmation:
            return Response(
                {"error": "Informe seu username para confirmar a exclusão."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if username_confirmation != request.user.username:
            return Response(
                {"error": "Username não confere."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        password = request.data.get('password')
        if not password or not request.user.check_password(password):
            return Response(
                {"error": "Informe sua senha atual para confirmar a exclusão."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.delete()
        return clear_refresh_cookie(Response(status=status.HTTP_204_NO_CONTENT))

@extend_schema(tags=['Usuários'], request=None, responses={
    201: OpenApiResponse(description='Passou a seguir'),
    204: OpenApiResponse(description='Deixou de seguir'),
    400: OpenApiResponse(description='Já segue / não segue / segue a si mesmo'),
})
class FollowView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        target = get_object_or_404(User, id=id)

        if target == request.user:
            return Response(
                {"error": "Você não pode seguir a si mesmo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            Follow.objects.create(follower=request.user, following=target)
        except IntegrityError:
            return Response(
                {"error": "Você já segue este usuário."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_201_CREATED)

    def delete(self, request, id):
        target = get_object_or_404(User, id=id)

        deleted, _ = Follow.objects.filter(follower=request.user, following=target).delete()

        if deleted == 0:
            return Response(
                {"error": "Você não segue este usuário."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

class FollowersListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = FollowerSerializer

    def get_queryset(self):
        user = get_object_or_404(User, id=self.kwargs['id'])
        return (
            Follow.objects
            .filter(following=user)
            .select_related('follower')
            .order_by('-created_at')
        )

class FollowingListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = FollowingSerializer

    def get_queryset(self):
        user = get_object_or_404(User, id=self.kwargs['id'])
        return (
            Follow.objects
            .filter(follower=user)
            .select_related('following')
            .order_by('-created_at')
        )

INVALID_RESET_LINK = "Link inválido ou expirado."


@extend_schema(
    tags=['Autenticação'],
    request=PasswordResetRequestSerializer,
    responses={
        200: OpenApiResponse(description='Resposta genérica: sempre 200, exista ou não uma conta com o e-mail'),
        400: OpenApiResponse(description='E-mail em formato inválido'),
        429: OpenApiResponse(description='Muitas solicitações (limite por IP)'),
    },
)
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'password_reset_request'

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        dispatch_password_reset_email(serializer.validated_data['email'])
        return Response(
            {"detail": "Se o e-mail estiver cadastrado, enviaremos as instruções para redefinir a senha."},
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=['Autenticação'],
    request=PasswordResetConfirmSerializer,
    responses={
        200: OpenApiResponse(description='Senha redefinida; todas as sessões (refresh tokens) foram revogadas'),
        400: OpenApiResponse(description='Link inválido/expirado ou senha fraca'),
        429: OpenApiResponse(description='Muitas tentativas (limite por IP)'),
    },
)
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'password_reset_confirm'

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"detail": INVALID_RESET_LINK}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        user = get_user_from_reset_link(data['uid'], data['token'])
        if user is None:
            return Response({"detail": INVALID_RESET_LINK}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reset_password(user, data['new_password'])
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        return clear_refresh_cookie(
            Response({"detail": "Senha redefinida com sucesso."}, status=status.HTTP_200_OK)
        )
