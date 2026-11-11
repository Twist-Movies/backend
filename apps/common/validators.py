from rest_framework import serializers

from .images import MAX_IMAGE_SIZE_MB, InvalidImage, open_validated


def validate_image_file(file):
    if file.size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise serializers.ValidationError(f"A imagem deve ter no máximo {MAX_IMAGE_SIZE_MB}MB.")

    # Valida o conteúdo real (o content-type do cliente não é confiável).
    try:
        open_validated(file)
    except InvalidImage as exc:
        raise serializers.ValidationError(str(exc))
    finally:
        file.seek(0)
