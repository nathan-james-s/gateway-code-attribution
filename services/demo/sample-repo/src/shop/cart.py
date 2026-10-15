"""A tiny shopping cart used by the Gateway Code Attribution demo."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Item:
    sku: str
    name: str
    price_cents: int
    quantity: int = 1


@dataclass
class Cart:
    items: list[Item] = field(default_factory=list)

    def add(self, item: Item) -> None:
        self.items.append(item)

    def subtotal_cents(self) -> int:
        return sum(item.price_cents * item.quantity for item in self.items)
