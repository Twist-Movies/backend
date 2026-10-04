import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from supabase import create_client
User = get_user_model()

_supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

def upload_avatar(file):
    bucket = "avatars"

    ext_map = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
    extension = ext_map.get(file.content_type, '.jpg')
    file_path = f"{uuid.uuid4()}{extension}"

    _supabase.storage.from_(bucket).upload(
        file_path,
        file.read(),
        {"content-type": file.content_type},
    )

    return _supabase.storage.from_(bucket).get_public_url(file_path)


def register_user(
    username, email, password, birth_date=None,
    first_name='', last_name='', bio=None, avatar=None,
):
    avatar_url = upload_avatar(avatar) if avatar else None

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

def update_profile(user, validated_data):
    avatar = validated_data.pop('avatar', None)
    if avatar:
        validated_data['avatar_url'] = upload_avatar(avatar)

    for field, value in validated_data.items():
        setattr(user, field, value)

    user.save()
    return user