from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    birth_date = serializers.DateField(required=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=500)
    avatar_url = serializers.URLField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'password',
            'birth_date', 'first_name', 'last_name', 'bio', 'avatar_url',
        ]
        read_only_fields = ['id']

    def validate_birth_date(self, value):
        if value > timezone.now().date():
            raise serializers.ValidationError("A data de nascimento não pode ser no futuro.")
        return value


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()  # aceita email OU username
    password = serializers.CharField(write_only=True)