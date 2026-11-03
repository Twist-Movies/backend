from django.urls import path

from .views import (
    MovieDiscoverView,
    PlaylistListCreateView,
    PlaylistDetailView,
    MovieDetailView,
    MovieReactionView,
    MovieSearchView,
    RatingView,
    WatchedMovieView,
    WatchlistView,
)
from .playlist_views import PlaylistMovieAddView, PlaylistMovieRemoveView
from .review_views import MovieReviewListCreateView, ReviewDetailView, ReviewLikeView

# O {tmdb_id} das rotas é o identificador do filme no TMDB; o filme local é
# criado/sincronizado automaticamente na primeira interação.
urlpatterns = [
    path('playlists/', PlaylistListCreateView.as_view(), name='playlist-list'),
    path('playlists/<int:pk>/', PlaylistDetailView.as_view(), name='playlist-detail'),
    path("playlists/<int:pk>/movies/", PlaylistMovieAddView.as_view()),
    path("playlists/<int:pk>/movies/<int:tmdb_id>/", PlaylistMovieRemoveView.as_view()),
    path("movies/search/", MovieSearchView.as_view()),
    path("movies/<int:tmdb_id>/", MovieDetailView.as_view()),
    path("movies/<int:tmdb_id>/watch/", WatchedMovieView.as_view()),
    path("movies/<int:tmdb_id>/watchlist/", WatchlistView.as_view()),
    path("movies/<int:tmdb_id>/rating/", RatingView.as_view()),
    path("movies/<int:tmdb_id>/reaction/", MovieReactionView.as_view()),
    path("movies/<int:tmdb_id>/reviews/", MovieReviewListCreateView.as_view()),
    path("reviews/<int:pk>/", ReviewDetailView.as_view()),
    path("reviews/<int:review_id>/like/", ReviewLikeView.as_view()),   
    path("movies/discover/", MovieDiscoverView.as_view()),
]
