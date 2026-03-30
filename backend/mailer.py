import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings


settings = get_settings()


def send_verification_email(recipient: str, code: str) -> None:
    if not settings.smtp_host or not settings.smtp_sender:
        logging.warning("SMTP is not configured. Verification code for %s: %s", recipient, code)
        return

    message = EmailMessage()
    message["Subject"] = "Код подтверждения рабочей почты"
    message["From"] = settings.smtp_sender
    message["To"] = recipient
    message.set_content(
        f"Ваш код подтверждения: {code}\n\n"
        f"Код действует {settings.email_verification_ttl_minutes} минут."
    )

    if settings.smtp_use_ssl:
        server_factory = smtplib.SMTP_SSL
    else:
        server_factory = smtplib.SMTP

    with server_factory(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        if settings.smtp_use_tls and not settings.smtp_use_ssl:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
