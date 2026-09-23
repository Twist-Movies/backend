from django.contrib.auth import get_user_model

User = get_user_model()


def register_user(username, email, password, birth_date=None):
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        birth_date=birth_date,
    )


def login_user(identifier, password):
    try:
        user = User.objects.get(email=identifier)
    except User.DoesNotExist:
        try:
            user = User.objects.get(username=identifier)
        except User.DoesNotExist:
            return None

    if user.check_password(password):
        return user
    return None