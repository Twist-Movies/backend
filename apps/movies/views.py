import logging
from django.shortcuts import render
from django.db.models import Prefetch, Q
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Playlist, PlaylistMovie, MovieReaction, Rating, WatchedMovie, Watchlist
from .permissions import IsOwnerOrReadOnly
from .playlist_serializers import PlaylistDetailSerializer
from .serializers import (
    PlaylistSerializer,
    MovieSearchQuerySerializer,
    MovieDiscoverQuerySerializer,
    PageQuerySerializer,
    RatingInputSerializer,
    ReactionInputSerializer,
)
from . import tmdb
from .services import (
    OFFICIAL_USERNAME,
    build_discover_params,
    build_movie_detail,
    build_person_detail,
    get_local_movie,
    get_or_sync_movie,
    serialize_search_page,
    sync_movie,
)

class PlaylistListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PlaylistSerializer

    def get_queryset(self):
        return (
            Playlist.objects
            .filter(owner=self.request.user)
            .select_related('owner')
            .order_by('-created_at')
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class PlaylistDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PlaylistDetailSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        queryset = Playlist.objects.select_related('owner').prefetch_related(
            Prefetch(
                'playlist_movies',
                queryset=PlaylistMovie.objects.select_related('movie').order_by('position', 'added_at'),
            )
        )
        if user.is_authenticated:
            return queryset.filter(Q(is_public=True) | Q(owner=user))
        return queryset.filter(is_public=True)


class OfficialPlaylistListView(generics.ListAPIView):
    """Playlists públicas curadas pela conta oficial (staff `twist`)."""
    permission_classes = [AllowAny]
    serializer_class = PlaylistSerializer

    def get_queryset(self):
        return (
            Playlist.objects
            .filter(is_public=True, owner__username=OFFICIAL_USERNAME, owner__is_staff=True)
            .select_related('owner')
            .order_by('id')
        )

logger = logging.getLogger(__name__)


def tmdb_error_response(exc):
    """Resposta genérica ao cliente; o detalhe do erro fica só no log do servidor."""
    if isinstance(exc, tmdb.TMDBNotFound):
        logger.info("TMDB: recurso não encontrado (%s)", exc)
        return Response({"error": "Filme não encontrado."}, status=status.HTTP_404_NOT_FOUND)
    logger.warning("TMDB indisponível: %s", exc)
    return Response(
        {"error": "Serviço de filmes indisponível no momento."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def delete_user_movie_entry(model, user, tmdb_id):
    movie = get_local_movie(tmdb_id)
    deleted = model.objects.filter(user=user, movie=movie).delete()[0] if movie else 0
    if not deleted:
        return Response({"error": "Registro não encontrado."}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=['Filmes'],
    parameters=[
        OpenApiParameter('q', str, description='Título a pesquisar', required=True),
        OpenApiParameter('page', int, description='Página de resultados do TMDB (1 a 500)'),
    ],
    responses={
        200: OpenApiResponse(description='Resultados da busca no TMDB'),
        400: OpenApiResponse(description='Parâmetro "q" ausente ou inválido'),
        503: OpenApiResponse(description='TMDB indisponível'),
    },
)
class MovieSearchView(APIView):
    throttle_scope = 'tmdb'
    permission_classes = [AllowAny]

    def get(self, request):
        query = MovieSearchQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return Response(query.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = tmdb.search_movies(query.validated_data["q"], query.validated_data["page"])
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        return Response(serialize_search_page(data))

@extend_schema(
    tags=['Filmes'],
    parameters=[
        OpenApiParameter('page', int, description='Página de resultados (1 a 500, padrão 1)'),
        OpenApiParameter('sort', str, enum=['popularity', 'rating', 'release_date'],
                         description='Ordenação (padrão: popularity)'),
        OpenApiParameter('genre', int, description='ID do gênero no TMDB (ex.: 18 = Drama)'),
        OpenApiParameter('decade', int, description='Ano inicial da década (ex.: 1990)'),
        OpenApiParameter('runtime_min', int, description='Duração mínima, em minutos'),
        OpenApiParameter('runtime_max', int, description='Duração máxima, em minutos'),
        OpenApiParameter('rating_min', float, description='Nota mínima, de 0 a 10 (escala do TMDB)'),
    ],
    responses={
        200: OpenApiResponse(description='Filmes do catálogo do TMDB, no mesmo formato da busca'),
        400: OpenApiResponse(description='Parâmetro inválido (erros por campo)'),
        503: OpenApiResponse(description='TMDB indisponível'),
    },
)
class MovieDiscoverView(APIView):
    throttle_scope = 'tmdb'
    permission_classes = [AllowAny]

    def get(self, request):
        query = MovieDiscoverQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return Response(query.errors, status=status.HTTP_400_BAD_REQUEST)

        params = build_discover_params(query.validated_data)
        try:
            data = tmdb.discover_movies(params, query.validated_data["page"])
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        return Response(serialize_search_page(data))

@extend_schema(
    tags=['Filmes'],
    responses={
        200: OpenApiResponse(description='Detalhes do filme, contadores do Twist e estado do usuário autenticado'),
        404: OpenApiResponse(description='Filme não encontrado no TMDB'),
        503: OpenApiResponse(description='TMDB indisponível'),
    },
)
class MovieDetailView(APIView):
    throttle_scope = 'tmdb'
    permission_classes = [AllowAny]

    def get(self, request, tmdb_id):
        try:
            data = tmdb.get_movie(tmdb_id)
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        movie = sync_movie(data)
        return Response(build_movie_detail(data, movie, request.user))


@extend_schema(
    tags=['Filmes'],
    parameters=[OpenApiParameter('page', int, description='Página de resultados (1 a 500, padrão 1)')],
    responses={
        200: OpenApiResponse(description='Filmes recomendados (ou similares), no mesmo formato da busca'),
        400: OpenApiResponse(description='Parâmetro inválido'),
        404: OpenApiResponse(description='Filme não encontrado no TMDB'),
        503: OpenApiResponse(description='TMDB indisponível'),
    },
)
class MovieRecommendationsView(APIView):
    throttle_scope = 'tmdb'
    permission_classes = [AllowAny]

    def get(self, request, tmdb_id):
        query = PageQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return Response(query.errors, status=status.HTTP_400_BAD_REQUEST)
        page = query.validated_data["page"]

        try:
            data = tmdb.get_recommendations(tmdb_id, page)
            if not data.get("results"):
                data = tmdb.get_similar(tmdb_id, page)
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        return Response(serialize_search_page(data))


@extend_schema(
    tags=['Filmes'],
    parameters=[OpenApiParameter('page', int, description='Página de resultados (1 a 500, padrão 1)')],
    responses={
        200: OpenApiResponse(description='Filmes em alta na semana, no mesmo formato da busca'),
        400: OpenApiResponse(description='Parâmetro inválido'),
        503: OpenApiResponse(description='TMDB indisponível'),
    },
)
class MovieTrendingView(APIView):
    throttle_scope = 'tmdb'
    permission_classes = [AllowAny]

    def get(self, request):
        query = PageQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return Response(query.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = tmdb.get_trending(query.validated_data["page"])
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        return Response(serialize_search_page(data))


@extend_schema(
    tags=['Filmes'],
    responses={
        200: OpenApiResponse(description='Dados da pessoa e até 20 filmes em que atuou, por popularidade'),
        404: OpenApiResponse(description='Pessoa não encontrada no TMDB'),
        503: OpenApiResponse(description='TMDB indisponível'),
    },
)
class PersonDetailView(APIView):
    throttle_scope = 'tmdb'
    permission_classes = [AllowAny]

    def get(self, request, tmdb_id):
        try:
            data = tmdb.get_person(tmdb_id)
            biography = data.get("biography") or ""
            if not biography.strip():
                try:
                    biography = tmdb.get_person(tmdb_id, language="en-US").get("biography") or ""
                except tmdb.TMDBError:
                    biography = ""  # o fallback é opcional
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        return Response(build_person_detail(data, biography))


class UserMovieEntryView(APIView):
    """Base para registros únicos usuário × filme (assistido, quero assistir).

    POST cria o registro (idempotente) e DELETE o remove.
    """
    permission_classes = [IsAuthenticated]
    model = None

    def post(self, request, tmdb_id):
        try:
            movie = get_or_sync_movie(tmdb_id)
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        _, created = self.model.objects.get_or_create(user=request.user, movie=movie)
        return Response(
            {"tmdb_id": tmdb_id, "movie_id": movie.id},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, tmdb_id):
        return delete_user_movie_entry(self.model, request.user, tmdb_id)


@extend_schema(
    tags=['Filmes'],
    request=None,
    responses={
        201: OpenApiResponse(description='Filme marcado como assistido'),
        200: OpenApiResponse(description='Filme já estava marcado como assistido'),
        204: OpenApiResponse(description='Registro de assistido removido'),
        401: OpenApiResponse(description='Não autenticado'),
        404: OpenApiResponse(description='Filme ou registro não encontrado'),
    },
)
class WatchedMovieView(UserMovieEntryView):
    model = WatchedMovie


@extend_schema(
    tags=['Filmes'],
    request=None,
    responses={
        201: OpenApiResponse(description='Filme adicionado à lista "Quero assistir"'),
        200: OpenApiResponse(description='Filme já estava na lista'),
        204: OpenApiResponse(description='Filme removido da lista'),
        401: OpenApiResponse(description='Não autenticado'),
        404: OpenApiResponse(description='Filme ou registro não encontrado'),
    },
)
class WatchlistView(UserMovieEntryView):
    model = Watchlist


class UserMovieValueView(APIView):
    """Base para valores únicos usuário × filme (avaliação, reação).

    PUT cria ou substitui o valor e DELETE o remove.
    """
    permission_classes = [IsAuthenticated]
    model = None
    input_serializer = None
    field = None

    def put(self, request, tmdb_id):
        serializer = self.input_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            movie = get_or_sync_movie(tmdb_id)
        except tmdb.TMDBError as exc:
            return tmdb_error_response(exc)

        value = serializer.validated_data[self.field]
        _, created = self.model.objects.update_or_create(
            user=request.user, movie=movie, defaults={self.field: value}
        )
        return Response(
            {"tmdb_id": tmdb_id, "movie_id": movie.id, self.field: value},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, tmdb_id):
        return delete_user_movie_entry(self.model, request.user, tmdb_id)


@extend_schema(
    tags=['Filmes'],
    request=RatingInputSerializer,
    responses={
        201: OpenApiResponse(description='Avaliação criada'),
        200: OpenApiResponse(description='Avaliação alterada'),
        204: OpenApiResponse(description='Avaliação removida'),
        400: OpenApiResponse(description='Nota fora da escala de 0,5 a 5 estrelas (passos de 0,5)'),
        401: OpenApiResponse(description='Não autenticado'),
        404: OpenApiResponse(description='Filme ou avaliação não encontrados'),
    },
)
class RatingView(UserMovieValueView):
    model = Rating
    input_serializer = RatingInputSerializer
    field = "stars"

    def patch(self, request, tmdb_id):
        return self.put(request, tmdb_id)


@extend_schema(
    tags=['Filmes'],
    request=ReactionInputSerializer,
    responses={
        201: OpenApiResponse(description='Reação registrada'),
        200: OpenApiResponse(description='Reação alterada (curtida ⇄ deslike)'),
        204: OpenApiResponse(description='Reação removida'),
        400: OpenApiResponse(description='Reação inválida (use LIKE ou DISLIKE)'),
        401: OpenApiResponse(description='Não autenticado'),
        404: OpenApiResponse(description='Filme ou reação não encontrados'),
    },
)
class MovieReactionView(UserMovieValueView):
    model = MovieReaction
    input_serializer = ReactionInputSerializer
    field = "reaction"
