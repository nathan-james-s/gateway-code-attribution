from shop.cart import Cart, Item


def test_subtotal() -> None:
    cart = Cart()
    cart.add(Item("TEA-1", "Green tea", 450, 2))
    cart.add(Item("MUG-1", "Mug", 1200))
    assert cart.subtotal_cents() == 2100
