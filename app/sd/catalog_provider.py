"""
Category/service provider.
Hardcoded for now; later replace with real SD catalog endpoints.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    type: str


@dataclass(frozen=True)
class Service:
    id: int
    name: str
    execution_timestamp: int
    category: Category


def get_default_category() -> Category:
    return Category(id=1, name="test", type="VS")


def get_default_service() -> Service:
    cat = get_default_category()
    return Service(id=1, name="test", execution_timestamp=10, category=cat)
