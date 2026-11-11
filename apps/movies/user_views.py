from django.contrib.auth import get_user_model
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny

User = get_user_model()

MIN_QUERY_LENGTH = 2


class UserPublicSerializer(serializers.ModelSerializer):
    """Campos públicos de um usuário (nunca inclui e-mail)."""

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "avatar_url", "bio"]
        read_only_fields = fields


@extend_schema(
    tags=['Usuários'],
    parameters=[OpenApiParameter('q', str, description='Trecho do username ou do nome (mín. 2 caracteres)', required=True)],
    responses={
        200: UserPublicSerializer(many=True),
        400: OpenApiResponse(description='Parâmetro "q" ausente ou com menos de 2 caracteres'),
    },
)
class UserSearchView(generics.ListAPIView):
    serializer_class = UserPublicSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        term = self.request.query_params.get("q", "").strip()
        if len(term) < MIN_QUERY_LENGTH:
            raise serializers.ValidationError({"q": f"Informe ao menos {MIN_QUERY_LENGTH} caracteres."})
        return User.objects.filter(
            Q(username__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term),
            is_active=True,
        ).order_by("username")
