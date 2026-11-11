import logging
import uuid

from django.conf import settings
from rest_framework import serializers
from rest_framework.exceptions import APIException
from supabase import create_client

from .images import InvalidImage, reencode

logger = logging.getLogger(__name__)

_supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


class StorageUnavailable(APIException):
    status_code = 503
    default_detail = "Não foi possível enviar a imagem agora. Tente novamente em instantes."
    default_code = "storage_unavailable"


def upload_image(file, bucket):
    """Reencoda a imagem (formato real, sem EXIF) e envia ao Supabase.

    Imagem inválida => 400; falha do Supabase => 503 (detalhe só no log).
    """
    try:
        data, content_type, extension = reencode(file)
    except InvalidImage as exc:
        raise serializers.ValidationError(str(exc))

    file_path = f"{uuid.uuid4()}{extension}"
    try:
        _supabase.storage.from_(bucket).upload(file_path, data, {"content-type": content_type})
        return _supabase.storage.from_(bucket).get_public_url(file_path)
    except Exception:
        logger.exception("Falha ao enviar imagem ao Supabase (bucket=%s)", bucket)
        raise StorageUnavailable()
