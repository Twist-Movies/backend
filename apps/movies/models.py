import uuid
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class Movie(models.Model):
    provider = models.CharField(max_length=50, default='TMDB')
    provider_movie_id = models.BigIntegerField()
    title = models.CharField(max_length=255)
    original_title = models.CharField(max_length=255, null=True, blank=True)
    overview = models.TextField(null=True, blank=True)
    poster_path = models.TextField(null=True, blank=True)
    backdrop_path = models.TextField(null=True, blank=True)
    release_date = models.DateField(null=True, blank=True)
    runtime_minutes = models.PositiveIntegerField(null=True, blank=True)
    rating_average = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)]
    )
    rating_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'movies'
        unique_together = ('provider', 'provider_movie_id')
        indexes = [
            models.Index(fields=['title'], name='idx_movies_title'),
        ]

    def __str__(self):
        return self.title


class WatchedMovie(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='watched_movies')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='watched_by')
    watched_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'watched_movies'
        unique_together = ('user', 'movie')
        indexes = [
            models.Index(fields=['user', '-watched_at'], name='idx_watched_user_date'),
            models.Index(fields=['movie'], name='idx_watched_movie'),
        ]


class Watchlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='watchlist')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='in_watchlists')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'watchlist'
        unique_together = ('user', 'movie')
        indexes = [
            models.Index(fields=['user'], name='idx_watchlist_user'),
        ]


class MovieReaction(models.Model):
    class ReactionChoices(models.TextChoices):
        LIKE = 'LIKE', 'Like'
        DISLIKE = 'DISLIKE', 'Dislike'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reactions')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='reactions')
    reaction = models.CharField(max_length=10, choices=ReactionChoices.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'movie_reactions'
        unique_together = ('user', 'movie')
        indexes = [
            models.Index(fields=['movie', 'reaction'], name='idx_reactions_movie_type'),
        ]


class Rating(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ratings')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='ratings')
    stars = models.SmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ratings'
        unique_together = ('user', 'movie')
        indexes = [
            models.Index(fields=['movie'], name='idx_ratings_movie'),
        ]


class Review(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='reviews')
    content = models.TextField()
    contains_spoiler = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reviews'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'movie'],
                condition=models.Q(is_active=True),
                name='one_active_review_per_user_movie'
            )
        ]
        indexes = [
            models.Index(fields=['movie', 'is_active'], name='idx_reviews_movie_active'),
        ]


class ReviewLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='liked_reviews')
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'review_likes'
        unique_together = ('user', 'review')
        indexes = [
            models.Index(fields=['-created_at'], name='idx_review_likes_date'),
        ]


class Playlist(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='playlists')
    name = models.CharField(max_length=150)
    description = models.CharField(max_length=1000, null=True, blank=True)
    cover_url = models.URLField(max_length=1000, null=True, blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'playlists'
        indexes = [
            models.Index(fields=['owner'], name='idx_playlists_owner'),
            models.Index(fields=['is_public'], condition=models.Q(is_public=True), name='idx_public_playlists'),
        ]


class PlaylistMovie(models.Model):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name='playlist_movies')
    movie = models.ForeignKey(Movie, on_delete=models.RESTRICT, related_name='in_playlists')
    position = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'playlist_movies'
        unique_together = ('playlist', 'movie')


class MovieRequest(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        IN_REVIEW = 'IN_REVIEW', 'In Review'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        DUPLICATE = 'DUPLICATE', 'Duplicate'

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='movie_requests')
    title = models.CharField(max_length=255)
    original_title = models.CharField(max_length=255, null=True, blank=True)
    release_year = models.SmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1888), MaxValueValidator(2200)]
    )
    external_url = models.URLField(max_length=1000, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    admin_notes = models.TextField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_requests'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_movie = models.ForeignKey(
        Movie, on_delete=models.SET_NULL, null=True, blank=True, related_name='originating_requests'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'movie_requests'
        indexes = [
            models.Index(fields=['status'], name='idx_movie_requests_status'),
            models.Index(fields=['requested_by'], name='idx_movie_requests_user'),
        ]