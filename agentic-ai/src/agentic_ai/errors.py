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


class KimiError(OllamaError):
    def __init__(self, message: str, *, category: str = "transport", ambiguous: bool = False):
        super().__init__(message)
        self.category = category
        self.ambiguous = ambiguous


class ToolError(AgenticError):
    pass


class RunInterrupted(AgenticError):
    pass


class MemoryError(AgenticError):
    pass


class MemoryConflictError(MemoryError):
    pass


class MemoryPermissionError(MemoryError):
    pass


class MemoryNotFoundError(MemoryError):
    pass


class IdentityError(AgenticError):
    pass
