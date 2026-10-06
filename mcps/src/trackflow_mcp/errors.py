from __future__ import annotations


class UpstreamError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def error_code(error: BaseException) -> str:
    if isinstance(error, UpstreamError):
        return error.code
    message = str(error)
    return message.split(":", 1)[0] if ":" in message else "INTERNAL_ERROR"