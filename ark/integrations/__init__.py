"""ARK-owned local integration adapters."""

from .contracts import IntegrationRequest, IntegrationResult
from .registry import IntegrationRegistry, build_local_registry

__all__ = [
    "IntegrationRegistry",
    "IntegrationRequest",
    "IntegrationResult",
    "build_local_registry",
]
