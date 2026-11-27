from ...core.http import ApiError


class WordCompatibilityError(ApiError):
    def __init__(self, message):
        super().__init__(message, 422, 42203)
