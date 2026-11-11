from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Review
from .serializers import MovieSummarySerializer

User = get_user_model()


class ReviewAuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "avatar_url"]
        read_only_fields = fields


class ReviewSerializer(serializers.ModelSerializer):
    """Leitura e escrita de comentários.

    `likes_count` e `liked_by_me` vêm de anotações do queryset
    (ver review_views.reviews_queryset).
    """

    author = ReviewAuthorSerializer(source="user", read_only=True)
    movie = MovieSummarySerializer(read_only=True)
    content = serializers.CharField(max_length=5000, trim_whitespace=True)
    likes_count = serializers.IntegerField(read_only=True, default=0)
    liked_by_me = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Review
        fields = [
            "id", "movie", "author", "content", "contains_spoiler",
            "likes_count", "liked_by_me", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "movie", "author", "likes_count", "liked_by_me", "created_at", "updated_at"]
