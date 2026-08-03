from __future__ import annotations


class ScannerError(RuntimeError):
    pass


class ScannerTransportError(ScannerError):
    def __init__(
        self,
        message: str,
        *,
        transient: bool,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.status_code = status_code
        self.response_body = response_body
