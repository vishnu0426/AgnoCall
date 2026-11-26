"""Send an email through the SMTP server from .env."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr


class ReportError(Exception):
    """A failure with a message that is safe to show in the UI (never contains a password)."""


def smtp_configured(s) -> bool:
    return bool(s.smtp_host.strip() and parseaddr(s.smtp_from)[1])


def send_email(s, to: list[str], subject: str, text: str, attachments: list[tuple[str, bytes, str]]) -> None:
    if not smtp_configured(s):
        raise ReportError("Email is not set up: put SMTP_HOST and SMTP_FROM in the server's .env and restart.")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, ", ".join(to), subject   # EmailMessage rejects header injection
    msg.set_content(text)
    for filename, data, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    host, port, timeout = s.smtp_host.strip(), s.smtp_port, s.smtp_timeout_seconds
    try:
        if s.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        with server:
            if s.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise ReportError("The email server rejected the SMTP username or password.")
    except smtplib.SMTPRecipientsRefused:
        raise ReportError("The email server refused every recipient address.")
    except smtplib.SMTPException as e:
        raise ReportError(f"The email server returned an error: {type(e).__name__}.")
    except (OSError, ssl.SSLError) as e:
        raise ReportError(f"Could not reach the email server {host}:{port} ({type(e).__name__}). "
                          "Check SMTP_HOST, SMTP_PORT and SMTP_SECURITY.")
