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


class ToolError(AgenticError):
    pass


class RunInterrupted(AgenticError):
    pass
