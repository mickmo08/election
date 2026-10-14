from __future__ import annotations

from .base import CountryAdapter
from .synthetic import SyntheticAdapter
from .us import UnitedStatesAdapter

ADAPTERS: dict[str, CountryAdapter] = {a.code: a for a in (UnitedStatesAdapter(), SyntheticAdapter())}


def get_adapter(code: str) -> CountryAdapter:
    try:
        return ADAPTERS[code]
    except KeyError as exc:
        raise KeyError(f"no country adapter registered for {code!r}") from exc
