from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.utils import timezone

from apps.accounts.models import Follow

from apps.common.validators import validate_image_file

User = get_user_model()

RESERVED_USERNAMES = frozenset({
    "twist", "admin", "administrator", "root", "suporte", "support", "staff",
    "moderador", "moderator", "api", "null", "undefined", "system", "oficial",
})

IDENTITY_EXTRA_KWARGS = {
    # Troca os UniqueValidator (sensíveis a caixa) pela checagem __iexact abaixo.
    "username": {"validators": [UnicodeUsernameValidator()]},
    "email": {"validators": []},
}


class UniqueIdentityMixin:
    """E-mail em minúsculas; e-mail/username únicos sem diferenciar caixa; nomes reservados."""

    def validate_email(self, value):
        value = value.strip().lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Já existe uma conta com este e-mail.")
        return value

    def validate_username(self, value):
        mantem_atual = self.instance is not None and self.instance.username == value
        if not mantem_atual:
            if value.lower() in RESERVED_USERNAMES:
                raise serializers.ValidationError("Este nome de usuário é reservado.")
            qs = User.objects.filter(username__iexact=value)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("Este nome de usuário já está em uso.")
        return value


class RegisterSerializer(UniqueIdentityMixin, serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    birth_date = serializers.DateField(required=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=500)
    avatar = serializers.ImageField(required=False, allow_null=True, write_only=True, validators=[validate_image_file],)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'password',
            'birth_date', 'first_name', 'last_name', 'bio', 'avatar',
        ]
        read_only_fields = ['id']
        extra_kwargs = IDENTITY_EXTRA_KWARGS

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

class UpdateProfileSerializer(UniqueIdentityMixin, serializers.ModelSerializer):
    # Obrigatória só ao trocar o e-mail (reautenticação); nunca é gravada.
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    avatar = serializers.ImageField(
        required=False, allow_null=True, write_only=True,
        validators=[validate_image_file],
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'birth_date', 'bio', 'avatar', 'current_password']
        extra_kwargs = IDENTITY_EXTRA_KWARGS

    def validate(self, attrs):
        current_password = attrs.pop('current_password', '')
        new_email = attrs.get('email')
        if new_email and self.instance is not None and new_email != self.instance.email.lower():
            if not current_password:
                raise serializers.ValidationError(
                    {'current_password': 'Informe sua senha atual para alterar o e-mail.'}
                )
            if not self.instance.check_password(current_password):
                raise serializers.ValidationError({'current_password': 'Senha atual incorreta.'})
        return attrs

    def validate_birth_date(self, value):
        if value and value > timezone.now().date():
            raise serializers.ValidationError("A data de nascimento não pode ser no futuro.")
        return value

class FollowerSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='follower.id')
    username = serializers.CharField(source='follower.username')
    first_name = serializers.CharField(source='follower.first_name')
    last_name = serializers.CharField(source='follower.last_name')
    avatar_url = serializers.CharField(source='follower.avatar_url')
    followed_at = serializers.DateTimeField(source='created_at')

    class Meta:
        model = Follow
        fields = ['id', 'username', 'first_name', 'last_name', 'avatar_url', 'followed_at']

class FollowingSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='following.id')
    username = serializers.CharField(source='following.username')
    first_name = serializers.CharField(source='following.first_name')
    last_name = serializers.CharField(source='following.last_name')
    avatar_url = serializers.CharField(source='following.avatar_url')
    followed_at = serializers.DateTimeField(source='created_at')

    class Meta:
        model = Follow
        fields = ['id', 'username', 'first_name', 'last_name', 'avatar_url', 'followed_at']

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
