from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'birth_date']
        read_only_fields = ['id']


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()  # aceita email OU username
    password = serializers.CharField(write_only=True)