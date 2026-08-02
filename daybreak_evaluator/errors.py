class EvaluatorError(RuntimeError):
    """Base evaluator integration error."""


class EvaluatorDeadlineExceeded(EvaluatorError):
    """The request could not complete before the evaluator response cutoff."""


class EvaluatorTransportError(EvaluatorError):
    """The provider request failed before a usable response was received."""


class EvaluatorResponseError(EvaluatorError):
    """The provider returned a response that cannot be accepted."""
