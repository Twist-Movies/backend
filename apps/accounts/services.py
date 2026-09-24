from django.contrib.auth import get_user_model

User = get_user_model()


def register_user(
    username, email, password, birth_date=None,
    first_name='', last_name='', bio=None, avatar_url=None,
):
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        birth_date=birth_date,
        first_name=first_name,
        last_name=last_name,
        bio=bio,
        avatar_url=avatar_url,
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