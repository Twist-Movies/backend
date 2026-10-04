from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

User = get_user_model()

def validate_avatar_file(file):
    max_size_mb = 5
    if file.size > max_size_mb * 1024 * 1024:
        raise serializers.ValidationError(f"A imagem deve ter no máximo {max_size_mb}MB.")

    allowed_types = ['image/jpeg', 'image/png', 'image/webp']
    if file.content_type not in allowed_types:
        raise serializers.ValidationError("Formato não suportado. Use JPEG, PNG ou WebP.")
    
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    birth_date = serializers.DateField(required=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=500)
    avatar = serializers.ImageField(required=False, allow_null=True, write_only=True, validators=[validate_avatar_file],)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'password',
            'birth_date', 'first_name', 'last_name', 'bio', 'avatar',
        ]
        read_only_fields = ['id']

    def validate_birth_date(self, value):
        if value > timezone.now().date():
            raise serializers.ValidationError("A data de nascimento não pode ser no futuro.")
        return value


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()  # aceita email OU username
    password = serializers.CharField(write_only=True)

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'birth_date', 'bio', 'avatar_url']
        read_only_fields = fields

class UpdateProfileSerializer(serializers.ModelSerializer):
    avatar = serializers.ImageField(
        required=False, allow_null=True, write_only=True,
        validators=[validate_avatar_file],
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'birth_date', 'bio', 'avatar']

    def validate_birth_date(self, value):
        if value and value > timezone.now().date():
            raise serializers.ValidationError("A data de nascimento não pode ser no futuro.")
        return value