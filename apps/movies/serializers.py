from rest_framework import serializers
from apps.common.storage import upload_image
from apps.common.validators import validate_image_file
from django.utils import timezone
from .models import Playlist, Movie, MovieReaction


COVER_BUCKET = "playlist-covers"


class PlaylistSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    cover = serializers.ImageField(
        required=False, allow_null=True, write_only=True,
        validators=[validate_image_file],
    )

    class Meta:
        model = Playlist
        fields = [
            'id', 'name', 'description', 'is_public', 'cover', 'cover_url',
            'owner_username', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'cover_url', 'owner_username', 'created_at', 'updated_at']

    def _apply_cover(self, validated_data):
        if 'cover' in validated_data:
            cover = validated_data.pop('cover')
            validated_data['cover_url'] = upload_image(cover, COVER_BUCKET) if cover else None

    def create(self, validated_data):
        self._apply_cover(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._apply_cover(validated_data)
        return super().update(instance, validated_data)


class MovieSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, trim_whitespace=True)
    page = serializers.IntegerField(required=False, default=1, min_value=1, max_value=500)

class MovieDiscoverQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(required=False, default=1, min_value=1, max_value=500)
    sort = serializers.ChoiceField(
        choices=["popularity", "rating", "release_date"], required=False, default="popularity"
    )
    genre = serializers.IntegerField(required=False, min_value=1)
    decade = serializers.IntegerField(required=False, min_value=1880)
    runtime_min = serializers.IntegerField(required=False, min_value=0)
    runtime_max = serializers.IntegerField(required=False, min_value=0)
    rating_min = serializers.FloatField(required=False, min_value=0, max_value=10)

    def validate_decade(self, value):
        if value % 10 != 0:
            raise serializers.ValidationError("Informe o ano inicial da década (ex.: 1990).")
        if value > timezone.localdate().year:
            raise serializers.ValidationError("A década não pode estar no futuro.")
        return value

    def validate(self, attrs):
        runtime_min = attrs.get("runtime_min")
        runtime_max = attrs.get("runtime_max")
        if runtime_min is not None and runtime_max is not None and runtime_min > runtime_max:
            raise serializers.ValidationError({"runtime_max": "Deve ser maior ou igual a runtime_min."})
        return attrs


class MovieSummarySerializer(serializers.ModelSerializer):
    """Representação resumida de um filme do catálogo local."""

    tmdb_id = serializers.IntegerField(source="provider_movie_id", read_only=True)

    class Meta:
        model = Movie
        fields = ["id", "tmdb_id", "title", "original_title", "poster_path", "release_date"]
        read_only_fields = fields


class RatingInputSerializer(serializers.Serializer):
    stars = serializers.IntegerField(min_value=1, max_value=5)


class ReactionInputSerializer(serializers.Serializer):
    reaction = serializers.ChoiceField(choices=MovieReaction.ReactionChoices.choices)
