from __future__ import annotations

from typing import Callable, TypeVar, get_type_hints


Endpoint = TypeVar("Endpoint", bound=Callable)


def resolve_annotations(endpoint: Endpoint) -> Endpoint:
    """Resolve deferred annotations before SlowAPI replaces endpoint globals."""
    endpoint.__annotations__ = get_type_hints(
        endpoint,
        globalns=endpoint.__globals__,
        localns=endpoint.__globals__,
        include_extras=True,
    )
    return endpoint
