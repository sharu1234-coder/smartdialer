from __future__ import annotations
import logging
from typing import Optional
from app.providers.base import TelecomProvider
from app.providers.circuit_breaker import CircuitBreaker
from app.core.enums import ProviderStatus

logger = logging.getLogger(__name__)

_providers: dict[str, TelecomProvider] = {}
_circuit_breakers: dict[str, CircuitBreaker] = {}


def register_provider(name: str, provider: TelecomProvider) -> None:
    _providers[name] = provider
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker()
    logger.info("Registered provider: %s", name)


def get_provider(name: str) -> TelecomProvider:
    provider = _providers.get(name)
    if not provider:
        raise ValueError(f"Provider '{name}' not registered")
    return provider


def get_circuit_breaker(name: str) -> CircuitBreaker:
    return _circuit_breakers.get(name, CircuitBreaker())


def get_all_providers() -> dict[str, TelecomProvider]:
    return dict(_providers)


def get_overall_health() -> ProviderStatus:
    """Return the best available provider health."""
    if not _providers:
        return ProviderStatus.UNHEALTHY
    statuses = []
    for name, provider in _providers.items():
        cb = _circuit_breakers.get(name)
        if cb and not cb.can_proceed():
            statuses.append(ProviderStatus.UNHEALTHY)
        else:
            statuses.append(provider.health_check())
    if any(s == ProviderStatus.HEALTHY for s in statuses):
        return ProviderStatus.HEALTHY
    if any(s == ProviderStatus.DEGRADED for s in statuses):
        return ProviderStatus.DEGRADED
    return ProviderStatus.UNHEALTHY


def get_provider_health_map() -> dict[str, str]:
    result = {}
    for name, provider in _providers.items():
        cb = _circuit_breakers.get(name)
        if cb and not cb.can_proceed():
            result[name] = ProviderStatus.UNHEALTHY.value
        else:
            result[name] = provider.health_check().value
    return result


def initialize_default_providers(
    provider_a_kwargs: Optional[dict] = None,
    provider_b_kwargs: Optional[dict] = None,
) -> None:
    from app.providers.provider_a import ProviderA
    from app.providers.provider_b import ProviderB

    pa_kwargs = provider_a_kwargs or {}
    pb_kwargs = provider_b_kwargs or {}

    register_provider("provider_a", ProviderA(**pa_kwargs))
    register_provider("provider_b", ProviderB(**pb_kwargs))
    logger.info("Default providers initialized: provider_a, provider_b")


def reset_providers() -> None:
    """Clear all registered providers (used in tests)."""
    _providers.clear()
    _circuit_breakers.clear()
