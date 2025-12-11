from django.core.mail.backends.smtp import EmailBackend


class NoSSLKeyfileEmailBackend(EmailBackend):
    """
    Overrides Django's SMTP backend so starttls() is called
    without keyfile/certfile arguments.
    """

    def open(self):
        if self.connection:
            return False

        try:
            super(EmailBackend, self).open()
        except AttributeError:
            pass

        if self.use_tls:
            self.connection.starttls()

        return True