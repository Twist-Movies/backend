from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegisterSerializer, LoginSerializer, UpdateProfileSerializer, UserSerializer
from .services import register_user, login_user, update_profile

from rest_framework.parsers import MultiPartParser, FormParser

from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from drf_spectacular.utils import extend_schema, OpenApiResponse

from django.shortcuts import get_object_or_404
from django.db import IntegrityError
from .models import Follow, User

@extend_schema(
    tags=['Autenticação'],
    request={'application/json': {'type': 'object', 'properties': {'refresh': {'type': 'string'}}}},
    responses={
        205: OpenApiResponse(description='Logout realizado — refresh token revogado'),
        400: OpenApiResponse(description='Token ausente ou já revogado'),
        401: OpenApiResponse(description='Access token ausente ou inválido'),
    },
)
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"error": "O campo 'refresh' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {"error": "Token inválido ou já revogado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_205_RESET_CONTENT)

@extend_schema(
    tags=['Autenticação'],
    request=RegisterSerializer,
    responses={
        201: OpenApiResponse(description='Usuário criado com sucesso'),
        400: OpenApiResponse(description='Erro de validação (e-mail/username duplicado, senha fraca, etc.)'),
    },
)
class RegisterView(APIView):
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
        200: OpenApiResponse(description='Login bem-sucedido — retorna access e refresh tokens'),
        401: OpenApiResponse(description='Credenciais inválidas'),
    },
)
class LoginView(APIView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = login_user(**serializer.validated_data)
        if user is None:
            return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "username": user.username,
            },
            status=status.HTTP_200_OK,
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

        user = update_profile(request.user, serializer.validated_data)
        return Response(UserSerializer(user).data)
    
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

        request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

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