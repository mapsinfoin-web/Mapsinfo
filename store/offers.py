"""
Admin-controlled Buy One Get One Free.

The admin maps ONE paid main product to the exact free gifts allowed (BogoOffer). The customer
adds the main product, then picks a gift in the cart (CartGift). Everything here is checked on
the server; the browser only says "I want product X as my gift" and we verify the rest.

* Gifts are only valid while the main product is in the cart and the offer is live.
* Gifts allowed = main quantity x free_per_main (capped by max_free_per_order).
* Gifts must be one of the products the admin listed, active and in stock.
* A gift is charged Rs.0; its normal price is shown crossed out.
"""
from collections import defaultdict
from decimal import Decimal

from .models import BogoOffer, CartGift, CartItem


def live_offers(now=None):
    offers = (BogoOffer.objects.filter(is_active=True)
              .select_related('main_product').prefetch_related('free_products'))
    return [offer for offer in offers if offer.is_live(now)]


def offer_by_main(offers):
    """{main_product_id: live offer}."""
    return {offer.main_product_id: offer for offer in sorted(offers, key=lambda o: o.pk)}


def attach_offers(products, offers=None):
    """Set product.offer (or None) so cards / detail page can show the badge."""
    offers = live_offers() if offers is None else offers
    mapping = offer_by_main(offers)
    for product in products:
        product.offer = mapping.get(product.pk)
    return products


def entitlement(offer, main_qty):
    """How many free gifts this offer gives for `main_qty` units of the main product."""
    allowed = main_qty * offer.free_per_main
    if offer.max_free_per_order is not None:
        allowed = min(allowed, offer.max_free_per_order)
    return allowed


def eligible_gifts(offer):
    """Gift choices the customer can actually pick right now (active and in stock)."""
    return [p for p in offer.free_products.all() if p.is_active and p.stock > 0]


def gift_slots_left(cart, offer):
    """How many more free gifts the customer may still pick for this offer."""
    main = CartItem.objects.filter(cart=cart, product_id=offer.main_product_id, is_active=True).first()
    if main is None:
        return 0
    used = sum(g.quantity for g in CartGift.objects.filter(cart=cart, offer=offer))
    return max(entitlement(offer, main.quantity) - used, 0)


def add_gift(cart, offer, gift_product_id):
    """
    Validate and add ONE free gift. Returns (ok, message).
    Used by the cart page buttons and by "Add to cart" on the product page.
    """
    main_item = CartItem.objects.filter(cart=cart, product_id=offer.main_product_id, is_active=True).first()
    if main_item is None:
        return False, "Add the main product to your cart first."

    product = next((p for p in offer.free_products.all() if p.pk == gift_product_id), None)
    if product is None or not product.is_active:
        return False, "That product is not one of the free gifts for this offer."

    gifts = list(CartGift.objects.filter(cart=cart, offer=offer))
    allowed = entitlement(offer, main_item.quantity)
    if sum(g.quantity for g in gifts) >= allowed:
        if allowed == 1 and gifts:
            # Only one gift allowed: choosing another one swaps it
            CartGift.objects.filter(cart=cart, offer=offer).delete()
            gifts = []
        else:
            return False, "You have already chosen all your free gifts. Remove one to pick another."

    paid_same = (CartItem.objects.filter(cart=cart, product_id=product.pk)
                 .values_list('quantity', flat=True).first() or 0)
    other_gifts = sum(g.quantity for g in CartGift.objects.filter(cart=cart, product_id=product.pk))
    if paid_same + other_gifts + 1 > product.stock:
        return False, f"Sorry, {product.title} is out of stock."

    existing = next((g for g in gifts if g.product_id == product.pk), None)
    if existing:
        existing.quantity += 1
        existing.save(update_fields=['quantity'])
    else:
        CartGift.objects.create(cart=cart, offer=offer, product=product, quantity=1)
    return True, f"{product.title} added to your cart as a FREE gift."


def auto_fill_single_gift(cart, offer):
    """
    If the offer has exactly ONE possible gift there is nothing to choose, so add it automatically.
    Returns the gift product when something was added, otherwise None.
    """
    choices = eligible_gifts(offer)
    if len(choices) != 1:
        return None
    product = choices[0]
    main_item = CartItem.objects.filter(cart=cart, product_id=offer.main_product_id, is_active=True).first()
    if main_item is None:
        return None

    allowed = entitlement(offer, main_item.quantity)
    gift = CartGift.objects.filter(cart=cart, offer=offer, product=product).first()
    have = gift.quantity if gift else 0
    paid_same = (CartItem.objects.filter(cart=cart, product_id=product.pk)
                 .values_list('quantity', flat=True).first() or 0)
    target = min(allowed, max(product.stock - paid_same, 0))
    if target <= have:
        return None
    if gift:
        gift.quantity = target
        gift.save(update_fields=['quantity'])
    else:
        CartGift.objects.create(cart=cart, offer=offer, product=product, quantity=target)
    return product


def sync_gifts(cart, offers=None):
    """
    Remove / trim gifts that are no longer valid and return messages explaining why.
    Called before every cart view and before checkout, so a gift can never outlive its main
    product, its offer, its stock or the allowed quantity.
    """
    notes = []
    gifts = list(cart.gifts.select_related('product').order_by('id'))
    if not gifts:
        return notes

    offers = live_offers() if offers is None else offers
    live_by_id = {offer.pk: offer for offer in offers}
    paid = {i.product_id: i.quantity for i in CartItem.objects.filter(cart=cart, is_active=True)}
    allocated = defaultdict(int)  # offer_id -> gift units kept
    reserved = defaultdict(int)   # product_id -> gift units kept (for the stock check)

    for gift in gifts:
        offer = live_by_id.get(gift.offer_id)
        product = gift.product
        reason = None
        if offer is None:
            reason = "that offer is no longer available"
        elif paid.get(offer.main_product_id, 0) <= 0:
            reason = f"{offer.main_product.title} is no longer in your cart"
        elif gift.product_id not in {p.pk for p in offer.free_products.all()}:
            reason = "it is no longer part of the offer"
        elif not product.is_active or product.stock <= 0:
            reason = "it is out of stock"

        if reason:
            gift.delete()
            notes.append(f"Free gift {product.title} was removed because {reason}.")
            continue

        slots = entitlement(offer, paid[offer.main_product_id]) - allocated[offer.pk]
        room = product.stock - paid.get(gift.product_id, 0) - reserved[gift.product_id]
        keep = min(gift.quantity, slots, room)
        if keep <= 0:
            gift.delete()
            notes.append(f"Free gift {product.title} was removed because you no longer qualify for it.")
            continue
        if keep < gift.quantity:
            gift.quantity = keep
            gift.save(update_fields=['quantity'])
            notes.append(f"Free gift {product.title} was reduced to {keep}.")
        allocated[offer.pk] += keep
        reserved[gift.product_id] += keep
    return notes


def calculate(cart_items, gifts=None, offers=None):
    """
    Price a cart. Returns dict: subtotal, discount, total, applied, gifts.
      subtotal = paid items + the normal price of the gifts
      discount = the normal price of the gifts (they are 100% off)
      total    = what the customer pays (paid items only)

    Sets on each paid cart item: offer, gift_entitled, gift_slots_left, my_gifts, gift_choices,
                                 line_total
    Sets on each gift:           original_total (normal price x qty)
    """
    items = list(cart_items)
    gifts = list(gifts or [])
    offers = live_offers() if offers is None else offers
    by_main = offer_by_main(offers)

    chosen = defaultdict(list)
    for gift in gifts:
        chosen[gift.offer_id].append(gift)

    subtotal = Decimal('0')
    for item in items:
        unit_price = getattr(item, 'unit_price', item.product.price)
        item.line_total = unit_price * item.quantity
        subtotal += item.line_total
        offer = by_main.get(item.product_id)
        item.offer = offer
        item.my_gifts, item.gift_entitled, item.gift_slots_left, item.gift_choices = [], 0, 0, []
        if offer:
            entitled = entitlement(offer, item.quantity)
            mine = chosen.get(offer.pk, [])
            item.my_gifts = mine
            item.gift_entitled = entitled
            item.gift_slots_left = max(entitled - sum(g.quantity for g in mine), 0)
            item.gift_choices = [p for p in offer.free_products.all() if p.is_active and p.stock > 0]

    discount = Decimal('0')
    applied = {}
    for gift in gifts:
        gift.original_total = gift.product.price * gift.quantity
        discount += gift.original_total
        entry = applied.setdefault(gift.offer_id, {
            'id': gift.offer_id, 'name': gift.offer.name,
            'main_product': gift.offer.main_product.title, 'gifts': [], 'discount': Decimal('0')})
        entry['gifts'].append({'product': gift.product.title, 'quantity': gift.quantity,
                               'value': str(gift.original_total)})
        entry['discount'] += gift.original_total
    for entry in applied.values():
        entry['discount'] = str(entry['discount'])

    subtotal += discount
    return {'subtotal': subtotal, 'discount': discount, 'total': subtotal - discount,
            'applied': list(applied.values()), 'gifts': gifts}