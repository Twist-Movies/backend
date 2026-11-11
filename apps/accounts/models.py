import uuid
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class TwistUserManager(UserManager):
    @classmethod
    def normalize_email(cls, email):
        """E-mail inteiro em minúsculas (o padrão do Django só ajusta o domínio)."""
        return (email or "").strip().lower()


class User(AbstractUser):
    objects = TwistUserManager()

    email = models.EmailField(unique=True)
    birth_date = models.DateField(null=True, blank=True)
    avatar_url = models.URLField(max_length=1000, null=True, blank=True)
    bio = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Mantemos email como campo principal de login se preferir
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users'

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username


class Follow(models.Model):
    follower = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='following_set'
    )
    following = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='followers_set'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'follows'
        unique_together = ('follower', 'following')
        constraints = [
            models.CheckConstraint(
                check=~models.Q(follower=models.F('following')),
                name='prevent_self_follow'
            )
        ]

    def __str__(self):
        return f"{self.follower} segue {self.following}"