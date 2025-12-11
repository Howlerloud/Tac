# tacweb/email_backend.py

import smtplib
from django.core.mail.backends.smtp import EmailBackend


class GmailSSLEmailBackend(EmailBackend):
    """
    Custom Email Backend for Gmail over SSL (port 465),
    avoiding unsupported keyfile/certfile arguments in Python 3.12.
    """

    def open(self):
        if self.connection:
            return False

        try:
            # IMPORTANT: Do NOT pass keyfile/certfile — Python 3.12 rejects them
            self.connection = smtplib.SMTP_SSL(
                self.host,
                self.port,
                timeout=self.timeout
            )

            if self.username and self.password:
                self.connection.login(self.username, self.password)

            return True

        except Exception:
            if self.connection is not None:
                try:
                    self.connection.close()
                except Exception:
                    pass
            self.connection = None
            raise
