class TelegramAPIError(Exception): pass
class TelegramBadRequest(TelegramAPIError): pass
class TelegramForbiddenError(TelegramAPIError): pass
class TelegramRetryAfter(TelegramAPIError):
    def __init__(self, retry_after=1): self.retry_after = retry_after; super().__init__("retry")
