import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def lowercase_emails(apps, schema_editor):
    """Coloca e-mails em minúsculas, pulando (e logando) os que gerariam conflito."""
    User = apps.get_model("accounts", "User")
    existentes = {u.email for u in User.objects.all().only("email")}
    for user in User.objects.all().order_by("pk"):
        lower = user.email.strip().lower()
        if lower == user.email:
            continue
        if lower in existentes:
            logger.warning("E-mail do usuário %s não normalizado: conflito com outra conta.", user.pk)
            continue
        existentes.discard(user.email)
        existentes.add(lower)
        user.email = lower
        user.save(update_fields=["email"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(lowercase_emails, migrations.RunPython.noop),
    ]
