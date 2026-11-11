"""Validação e reencode de imagens enviadas (formato real, dimensões, sem EXIF)."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_SIZE_MB = 5
MAX_IMAGE_DIMENSION = 4096

# formato real (Pillow) -> (content-type, extensão)
ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class InvalidImage(Exception):
    """Imagem inválida; a mensagem (pt-BR) pode ser mostrada ao usuário."""


def open_validated(file):
    """Abre com Pillow e valida formato real e dimensões. Não decodifica os pixels."""
    try:
        file.seek(0)
        image = Image.open(file)
    except Image.DecompressionBombError:
        raise InvalidImage(f"A imagem deve ter no máximo {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} pixels.")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise InvalidImage("O arquivo enviado não é uma imagem válida.")

    if image.format not in ALLOWED_FORMATS:
        raise InvalidImage("Formato não suportado. Use JPEG, PNG ou WebP.")
    width, height = image.size
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise InvalidImage(f"A imagem deve ter no máximo {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} pixels.")
    return image


def reencode(file):
    """Retorna (bytes, content_type, extensão) da imagem reencodada, sem EXIF/metadados."""
    image = open_validated(file)
    real_format = image.format
    try:
        image.load()
        image = ImageOps.exif_transpose(image)  # aplica a rotação do EXIF antes de descartá-lo
        if real_format == "JPEG" and image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = io.BytesIO()
        save_kwargs = {"quality": 90} if real_format in ("JPEG", "WEBP") else {}
        image.save(buffer, format=real_format, **save_kwargs)  # sem exif=: metadados descartados
    except Image.DecompressionBombError:
        raise InvalidImage(f"A imagem deve ter no máximo {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} pixels.")
    except (OSError, ValueError, SyntaxError):
        raise InvalidImage("Não foi possível processar a imagem enviada.")
    content_type, extension = ALLOWED_FORMATS[real_format]
    return buffer.getvalue(), content_type, extension
