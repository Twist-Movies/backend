from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.db.models import Count, Exists, OuterRef, Value
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView

from . import tmdb
from .models import Review, ReviewLike
from .permissions import IsAuthorOrReadOnly
from .review_serializers import ReviewSerializer
from .services import TMDB_PROVIDER, get_or_sync_movie
from .views import tmdb_error_response

User = get_user_model()

DUPLICATE_REVIEW_ERROR = {"error": "Você já possui um comentário ativo para este filme."}


def reviews_queryset(user):
    queryset = (
        Review.objects.filter(is_active=True)
        .select_related("user", "movie")
        .annotate(likes_count=Count("likes"))
    )
    if user.is_authenticated:
        liked = ReviewLike.objects.filter(review=OuterRef("pk"), user=user)
        return queryset.annotate(liked_by_me=Exists(liked))
    return queryset.annotate(liked_by_me=Value(False))


@extend_schema(
    tags=['Comentários'],
    responses={200: ReviewSerializer(many=True), 401: OpenApiResponse(description='Não autenticado')},
    description='Comentários ativos de quem o usuário segue, dos mais recentes para os mais antigos.',
)
class FeedView(generics.ListAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return reviews_queryset(self.request.user).filter(
            user__followers_set__follower=self.request.user,
        ).order_by("-created_at", "-id")


@extend_schema(
    tags=['Comentários'],
    responses={200: ReviewSerializer(many=True), 404: OpenApiResponse(description='Usuário não encontrado')},
    description='Comentários ativos de um usuário, dos mais recentes para os mais antigos.',
)
class UserReviewListView(generics.ListAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        get_object_or_404(User, pk=self.kwargs["id"])
        return reviews_queryset(self.request.user).filter(
            user_id=self.kwargs["id"],
        ).order_by("-created_at", "-id")


@extend_schema_view(
    get=extend_schema(
        tags=['Resenhas'],
        responses={200: ReviewSerializer(many=True)},
        description='Lista as resenhas ativas do filme, das mais recentes para as mais antigas.',
    ),
    post=extend_schema(
        tags=['Resenhas'],
        request=ReviewSerializer,
        responses={
            201: ReviewSerializer,
            400: OpenApiResponse(description='Dados inválidos ou o usuário já possui resenha ativa para o filme'),
            401: OpenApiResponse(description='Não autenticado'),
            404: OpenApiResponse(description='Filme não encontrado no TMDB'),
        },
    ),
)
class MovieReviewListCreateView(generics.ListCreateAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return reviews_queryset(self.request.user).filter(
            movie__provider=TMDB_PROVIDER,
            movie__provider_movie_id=self.kwargs["tmdb_id"],
        ).order_by("-created_at")

    def create(self, request, tmdb_id):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            movie = get_or_sync_movie(tmdb_id)
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        if Review.objects.filter(user=request.user, movie=movie, is_active=True).exists():
            return Response(DUPLICATE_REVIEW_ERROR, status=status.HTTP_400_BAD_REQUEST)
        try:
            review = serializer.save(user=request.user, movie=movie)
        except IntegrityError:
            return Response(DUPLICATE_REVIEW_ERROR, status=status.HTTP_400_BAD_REQUEST)

        review = reviews_queryset(request.user).get(pk=review.pk)
        return Response(self.get_serializer(review).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=['Resenhas'], responses={200: ReviewSerializer, 404: OpenApiResponse(description='Resenha não encontrada')}),
    patch=extend_schema(
        tags=['Resenhas'],
        request=ReviewSerializer,
        responses={
            200: ReviewSerializer,
            400: OpenApiResponse(description='Dados inválidos'),
            401: OpenApiResponse(description='Não autenticado'),
            403: OpenApiResponse(description='Apenas o autor pode editar a resenha'),
            404: OpenApiResponse(description='Resenha não encontrada'),
        },
    ),
    delete=extend_schema(
        tags=['Resenhas'],
        responses={
            204: OpenApiResponse(description='Resenha excluída'),
            401: OpenApiResponse(description='Não autenticado'),
            403: OpenApiResponse(description='Apenas o autor pode excluir a resenha'),
            404: OpenApiResponse(description='Resenha não encontrada'),
        },
    ),
)
class ReviewDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsAuthorOrReadOnly]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return reviews_queryset(self.request.user)

    def perform_destroy(self, instance):
        # Exclusão lógica: libera a restrição de uma resenha ativa por filme.
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


@extend_schema(
    tags=['Resenhas'],
    request=None,
    responses={
        201: OpenApiResponse(description='Resenha curtida'),
        200: OpenApiResponse(description='A resenha já estava curtida'),
        204: OpenApiResponse(description='Curtida removida'),
        401: OpenApiResponse(description='Não autenticado'),
        404: OpenApiResponse(description='Resenha ou curtida não encontrada'),
    },
)
class ReviewLikeView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_review(self, review_id):
        return Review.objects.filter(pk=review_id, is_active=True).first()

    def post(self, request, review_id):
        review = self._get_review(review_id)
        if review is None:
            return Response({"error": "Resenha não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        _, created = ReviewLike.objects.get_or_create(user=request.user, review=review)
        return Response(
            {"review_id": review.id, "likes_count": review.likes.count()},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, review_id):
        deleted, _ = ReviewLike.objects.filter(user=request.user, review_id=review_id).delete()
        if not deleted:
            return Response({"error": "Curtida não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
