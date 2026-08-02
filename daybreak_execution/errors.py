from __future__ import annotations


class ExecutionError(RuntimeError):
    pass


class BrokerNotFound(ExecutionError):
    pass


class BrokerTransportError(ExecutionError):
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
