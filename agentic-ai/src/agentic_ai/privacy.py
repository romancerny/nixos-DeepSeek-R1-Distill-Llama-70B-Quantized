from __future__ import annotations

from .config import Config
from .errors import MemoryPermissionError


CLASSIFICATION_RANK = {"public": 0, "shareable": 1, "internal": 2, "private": 3}
HOSTED_CLASSIFICATIONS = {"public", "shareable"}


class PrivacyPolicy:
    @staticmethod
    def most_sensitive(*classifications: str) -> str:
        if not classifications:
            return "public"
        unknown = set(classifications) - set(CLASSIFICATION_RANK)
        if unknown:
            raise MemoryPermissionError(f"Unknown data classifications: {sorted(unknown)}")
        return max(classifications, key=CLASSIFICATION_RANK.__getitem__)

    @staticmethod
    def hosted_allowed(classification: str) -> bool:
        return classification in HOSTED_CLASSIFICATIONS

    @classmethod
    def require_inference(
        cls,
        config: Config,
        model: str,
        classification: str,
        *,
        approved: bool,
        dreaming: bool = False,
    ) -> None:
        if config.backend_for_model(model) != "kimi":
            return
        if not config.kimi.enabled or not config.kimi.approved or not approved:
            raise MemoryPermissionError(
                "Hosted inference requires Kimi configuration approval and an explicit "
                "command/run approval"
            )
        if not cls.hosted_allowed(classification):
            raise MemoryPermissionError(
                f"Hosted inference is denied for {classification} context; use a local model"
            )
        if dreaming and not (config.dream.allow_hosted and config.kimi.allow_dreaming):
            raise MemoryPermissionError("Hosted dreaming requires both explicit opt-ins")

    @classmethod
    def filter_for_model(
        cls, config: Config, model: str, items: list[dict]
    ) -> list[dict]:
        if config.backend_for_model(model) != "kimi":
            return items
        return [
            item
            for item in items
            if cls.hosted_allowed(item.get("classification", "private"))
        ]
