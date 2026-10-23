class AgenticError(Exception):
    """Base error with a stable category for reports and recovery."""


class ConfigurationError(AgenticError):
    pass


class ProtocolError(AgenticError):
    pass


class PlanValidationError(AgenticError):
    pass


class StorageError(AgenticError):
    pass


class ResidencyError(AgenticError):
    pass


class OllamaError(AgenticError):
    pass


class LlamaCppError(OllamaError):
    """Inference-backend failure from the llama.cpp server.

    Subclasses OllamaError so operational-error handling treats both
    inference backends uniformly.
    """


class ToolError(AgenticError):
    pass


class RunInterrupted(AgenticError):
    pass
