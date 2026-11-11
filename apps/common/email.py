import logging
from email.utils import parseaddr

import httpx
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS = 5.0

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_TIMEOUT_SECONDS = 5.0


class EmailDeliveryError(Exception):
    """Falha ao enviar e-mail pelo provedor (Resend ou Brevo)."""


class ResendEmailBackend(BaseEmailBackend):
    """Backend de e-mail do Django que envia via API HTTP do Resend.

    Lê a chave de `settings.RESEND_API_KEY` (nunca fica no código).
    """

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages or []:
            try:
                self._send(message)
                sent += 1
            except Exception as exc:
                logger.error("Falha ao enviar e-mail via Resend: %s", exc)
                if not self.fail_silently:
                    if isinstance(exc, EmailDeliveryError):
                        raise
                    raise EmailDeliveryError(f"Falha ao enviar e-mail via Resend: {exc}") from exc
        return sent

    def _send(self, message):
        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            raise EmailDeliveryError("RESEND_API_KEY não configurada.")
        if not message.recipients():
            return

        payload = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to),
            "subject": message.subject,
            "text": message.body,
        }
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)

        response = httpx.post(
            RESEND_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=RESEND_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise EmailDeliveryError(f"Resend respondeu {response.status_code}: {response.text[:200]}")



class BrevoEmailBackend(BaseEmailBackend):
    """Backend de e-mail do Django que envia via API HTTP do Brevo.

    Lê a chave de `settings.BREVO_API_KEY` (nunca fica no código). O remetente
    (`DEFAULT_FROM_EMAIL`) precisa estar verificado no painel do Brevo; não é
    preciso ter domínio próprio.
    """

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages or []:
            try:
                self._send(message)
                sent += 1
            except Exception as exc:
                logger.error("Falha ao enviar e-mail via Brevo: %s", exc)
                if not self.fail_silently:
                    if isinstance(exc, EmailDeliveryError):
                        raise
                    raise EmailDeliveryError(f"Falha ao enviar e-mail via Brevo: {exc}") from exc
        return sent

    def _send(self, message):
        api_key = getattr(settings, "BREVO_API_KEY", "")
        if not api_key:
            raise EmailDeliveryError("BREVO_API_KEY não configurada.")
        if not message.recipients():
            return

        nome, endereco = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)
        sender = {"email": endereco}
        if nome:
            sender["name"] = nome

        payload = {
            "sender": sender,
            "to": [{"email": email} for email in message.to],
            "subject": message.subject,
            "textContent": message.body,
        }
        if message.cc:
            payload["cc"] = [{"email": email} for email in message.cc]
        if message.bcc:
            payload["bcc"] = [{"email": email} for email in message.bcc]

        response = httpx.post(
            BREVO_URL,
            json=payload,
            headers={"api-key": api_key, "accept": "application/json"},
            timeout=BREVO_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise EmailDeliveryError(f"Brevo respondeu {response.status_code}: {response.text[:200]}")
