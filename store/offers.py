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

from .models import BogoOffer, CartGift, CartItem, QuantityOffer


def live_quantity_offers(now=None):
    """Return all currently active and unexpired progressive quantity offers."""
    try:
        offers = (QuantityOffer.objects.filter(is_active=True)
                  .prefetch_related('categories', 'products'))
        return [offer for offer in offers if offer.is_live(now)]
    except Exception:
        return []


def get_quantity_offer_for_product(product, offers=None):
    """
    Find the applicable live progressive tiered discount offer for a product.
    Uses prefetched .products.all() and .categories.all() in Python to avoid N+1 SQL queries.
    """
    if product is None:
        return None
    offers = live_quantity_offers() if offers is None else offers
    # 1. Direct product match first (most specific)
    for offer in offers:
        if not offer.apply_to_all and any(p.pk == product.pk for p in offer.products.all()):
            return offer

    # 2. Category match second
    if product.category_id:
        for offer in offers:
            if not offer.apply_to_all and any(c.pk == product.category_id for c in offer.categories.all()):
                return offer

    # 3. Global apply_to_all fallback
    for offer in offers:
        if offer.apply_to_all:
            return offer
    return None


def live_offers(now=None):
    offers = (BogoOffer.objects.filter(is_active=True)
              .select_related('main_product').prefetch_related('free_products'))
    return [offer for offer in offers if offer.is_live(now)]


def offer_by_main(offers):
    """{main_product_id: live offer}."""
    return {offer.main_product_id: offer for offer in sorted(offers, key=lambda o: o.pk)}


def attach_offers(products, offers=None, quantity_offers=None):
    """Set product.offer and product.quantity_offer (or None) so cards / detail page can show the badges."""
    offers = live_offers() if offers is None else offers
    q_offers = live_quantity_offers() if quantity_offers is None else quantity_offers
    mapping = offer_by_main(offers)
    for product in products:
        product.offer = mapping.get(product.pk)
        product.quantity_offer = get_quantity_offer_for_product(product, q_offers)
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
    Only applies to 100% free gifts (not percentage discount bundles).
    """
    if offer.discount_percentage and offer.discount_percentage < 100:
        return None
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


def calculate(cart_items, gifts=None, offers=None, quantity_offers=None):
    """
    Price a cart. Returns dict: subtotal, discount, total, applied, gifts.
      subtotal = sum of (undiscounted line totals) + the normal price of the gifts
      discount = progressive tiered quantity discounts + normal price of free gifts
      total    = subtotal - discount (what the customer actually pays)

    Sets on each paid cart item:
      - unit_price: variant price or product price
      - line_total: payable amount for this item
      - original_line_total: undiscounted line total
      - tiered_discount: progressive savings on this item
      - tiered_offer: applied QuantityOffer (if any)
      - offer: applied BogoOffer (if any)
      - gift_entitled, gift_slots_left, my_gifts, gift_choices
    """
    items = list(cart_items)
    gifts = list(gifts or [])
    offers = live_offers() if offers is None else offers
    q_offers = live_quantity_offers() if quantity_offers is None else quantity_offers
    by_main = offer_by_main(offers)

    chosen = defaultdict(list)
    for gift in gifts:
        chosen[gift.offer_id].append(gift)

    subtotal = Decimal('0')
    discount = Decimal('0')
    applied = {}
    auto_free_items = []
    paid_qty_by_product = defaultdict(int)
    items_by_product = {}
    for it in items:
        paid_qty_by_product[it.product_id] += it.quantity
        items_by_product.setdefault(it.product_id, []).append(it)

    for item in items:
        unit_price = getattr(item, 'unit_price', getattr(item.product, 'price', Decimal('0')))
        item.original_line_total = unit_price * item.quantity
        item.tiered_discount = Decimal('0')
        item.tiered_offer = None
        item.bundle_discount = Decimal('0')
        item.bundle_offer = None
        item.product_offer_discount = Decimal('0')
        item.product_offer_label = ''
        item.product_offer_nudge = ''
        item.product_offer_partner_cta = None
        item.auto_free_items = []

        # Check progressive tiered quantity discount (skip if product has its own Offer 2 or Offer 3)
        prod_offer_type = getattr(item.product, 'offer_type', 'NONE')
        q_offer = None if prod_offer_type in ('BOGO', 'SECOND_10_OFF', 'BUY_2_10_OFF') else get_quantity_offer_for_product(item.product, q_offers)
        if q_offer and item.quantity >= 2:
            undisc, tier_disc, pay, breakdown = q_offer.calculate_units(unit_price, item.quantity)
            item.tiered_offer = q_offer
            item.tiered_discount = tier_disc
            item.line_total = pay
            discount += tier_disc

            entry_key = f"tiered_{q_offer.pk}"
            if entry_key not in applied:
                applied[entry_key] = {
                    'id': entry_key,
                    'name': q_offer.name,
                    'type': 'tiered',
                    'badge': q_offer.badge_text,
                    'discount': Decimal('0'),
                    'items': []
                }
            applied[entry_key]['discount'] += tier_disc
            applied[entry_key]['items'].append({
                'product': item.product.title,
                'quantity': item.quantity,
                'discount': str(tier_disc)
            })
        else:
            item.line_total = item.original_line_total

        subtotal += item.original_line_total

        # BOGO offer checks (100% free gift offers)
        offer = by_main.get(item.product_id)
        item.offer = offer
        item.my_gifts, item.gift_entitled, item.gift_slots_left, item.gift_choices = [], 0, 0, []
        if offer and (not offer.discount_percentage or offer.discount_percentage >= 100):
            entitled = entitlement(offer, item.quantity)
            mine = chosen.get(offer.pk, [])
            item.my_gifts = mine
            item.gift_entitled = entitled
            item.gift_slots_left = max(entitled - sum(g.quantity for g in mine), 0)
            item.gift_choices = [p for p in offer.free_products.all() if p.is_active and p.stock > 0]

    # Cross-product percentage bundle discounts (e.g. Buy Testing1, get ABC at 10% off)
    for main_item in items:
        offer = by_main.get(main_item.product_id)
        if not offer or not offer.discount_percentage or offer.discount_percentage >= 100:
            continue

        bundle_target_ids = set(offer.free_products.values_list('pk', flat=True))
        if not bundle_target_ids:
            continue

        allowed_bundle_units = entitlement(offer, main_item.quantity)
        for target_item in items:
            if target_item.product_id in bundle_target_ids and target_item.product_id != main_item.product_id:
                eligible_qty = min(target_item.quantity, allowed_bundle_units)
                if eligible_qty > 0:
                    unit_p = getattr(target_item, 'unit_price', getattr(target_item.product, 'price', Decimal('0')))
                    pct = offer.discount_percentage / Decimal('100')
                    bundle_saving = (unit_p * pct * eligible_qty).quantize(Decimal('0.01'))
                    target_item.bundle_discount += bundle_saving
                    target_item.bundle_offer = offer
                    target_item.line_total = max(target_item.line_total - bundle_saving, Decimal('0'))
                    discount += bundle_saving

                    entry_key = f"bundle_{offer.pk}_{target_item.product_id}"
                    if entry_key not in applied:
                        applied[entry_key] = {
                            'id': entry_key,
                            'name': offer.name or f"Bundle Deal: Buy {main_item.product.title} & Get {int(offer.discount_percentage)}% Off {target_item.product.title}",
                            'type': 'bundle',
                            'badge': f"Bundle: {int(offer.discount_percentage)}% Off",
                            'discount': Decimal('0'),
                            'items': []
                        }
                    applied[entry_key]['discount'] += bundle_saving
                    applied[entry_key]['items'].append({
                        'product': target_item.product.title,
                        'quantity': eligible_qty,
                        'discount': str(bundle_saving)
                    })
                    allowed_bundle_units -= eligible_qty
                    if allowed_bundle_units <= 0:
                        break

    # Product-level Offers (Offers 1-4 configured directly on Product in Admin)
    reserved_free = defaultdict(int)
    for item in items:
        prod = item.product
        otype = getattr(prod, 'offer_type', 'NONE')
        unit_price = getattr(item, 'unit_price', getattr(prod, 'price', Decimal('0')))

        if otype == 'BOGO':
            free_prod = prod.offer_partner_product if (prod.offer_partner_product_id and prod.offer_partner_product.is_active) else prod
            room = max(free_prod.stock - paid_qty_by_product.get(free_prod.pk, 0) - reserved_free[free_prod.pk], 0)
            free_qty = min(item.quantity, room)
            if free_qty > 0:
                reserved_free[free_prod.pk] += free_qty
                free_unit_price = getattr(free_prod, 'price', Decimal('0'))
                free_total = free_unit_price * free_qty
                subtotal += free_total
                discount += free_total
                free_entry = {
                    'product': free_prod,
                    'quantity': free_qty,
                    'unit_price': free_unit_price,
                    'original_total': free_total,
                    'main_product': prod,
                }
                item.auto_free_items.append(free_entry)
                auto_free_items.append(free_entry)
                key = f"prod_bogo_{prod.pk}"
                if key not in applied:
                    applied[key] = {
                        'id': key,
                        'name': f"Buy 1 Get 1 Free ({free_prod.title})",
                        'type': 'product_bogo',
                        'badge': "Buy 1 Get 1 FREE",
                        'discount': Decimal('0'),
                    }
                applied[key]['discount'] += free_total
            else:
                item.product_offer_nudge = f"Free item ({free_prod.title}) is currently out of stock for additional free units."

        elif otype == 'SECOND_10_OFF':
            if item.quantity >= 2:
                pairs = item.quantity // 2
                saving = (unit_price * Decimal('0.10') * pairs).quantize(Decimal('0.01'))
                if saving > 0:
                    item.product_offer_discount += saving
                    item.product_offer_label = "Offer 2: 10% Off 2nd Item"
                    item.line_total = max(item.line_total - saving, Decimal('0'))
                    discount += saving
                    key = f"prod_sec10_{prod.pk}"
                    applied[key] = {
                        'id': key,
                        'name': f"Buy 1 Get 10% Off 2nd Item ({prod.title})",
                        'type': 'product_offer',
                        'badge': "Buy 1 Get 10% Off 2nd Item",
                        'discount': saving,
                    }
            else:
                item.product_offer_nudge = "Add 1 more to get 10% OFF on the 2nd item!"

        elif otype == 'BUY_2_10_OFF':
            if item.quantity >= 2:
                saving = (item.original_line_total * Decimal('0.10')).quantize(Decimal('0.01'))
                if saving > 0:
                    item.product_offer_discount += saving
                    item.product_offer_label = "Offer 3: Buy 2 Get 10% Off"
                    item.line_total = max(item.line_total - saving, Decimal('0'))
                    discount += saving
                    key = f"prod_buy2_{prod.pk}"
                    applied[key] = {
                        'id': key,
                        'name': f"Buy 2 Get 10% Off ({prod.title})",
                        'type': 'product_offer',
                        'badge': "Buy 2 Get 10% Off",
                        'discount': saving,
                    }
            else:
                item.product_offer_nudge = "Add 1 more to get 10% OFF on both!"

        elif otype == 'CROSS_10_OFF' and prod.offer_partner_product_id:
            partner = prod.offer_partner_product
            partner_items = items_by_product.get(partner.pk, [])
            if partner_items:
                partner_item = partner_items[0]
                pair_qty = min(item.quantity, partner_item.quantity)
                if pair_qty > 0:
                    p_unit_price = getattr(partner_item, 'unit_price', getattr(partner, 'price', Decimal('0')))
                    saving_x = (unit_price * Decimal('0.10') * pair_qty).quantize(Decimal('0.01'))
                    saving_y = (p_unit_price * Decimal('0.10') * pair_qty).quantize(Decimal('0.01'))
                    total_pair_saving = saving_x + saving_y
                    if saving_x > 0:
                        item.product_offer_discount += saving_x
                        item.product_offer_label = f"Combo 10% Off (with {partner.title})"
                        item.line_total = max(item.line_total - saving_x, Decimal('0'))
                    if saving_y > 0:
                        partner_item.product_offer_discount += saving_y
                        partner_item.product_offer_label = f"Combo 10% Off (with {prod.title})"
                        partner_item.line_total = max(partner_item.line_total - saving_y, Decimal('0'))
                    discount += total_pair_saving
                    key = f"prod_cross_{prod.pk}_{partner.pk}"
                    applied[key] = {
                        'id': key,
                        'name': f"Buy {prod.title} + {partner.title} — 10% Off Both",
                        'type': 'product_offer',
                        'badge': "Combo Deal: 10% Off Both",
                        'discount': total_pair_saving,
                    }
            else:
                item.product_offer_nudge = f"Add {partner.title} to get 10% OFF on BOTH products!"
                item.product_offer_partner_cta = partner

    for gift in gifts:
        gift.original_total = gift.product.price * gift.quantity
        subtotal += gift.original_total
        discount += gift.original_total
        entry = applied.setdefault(gift.offer_id, {
            'id': gift.offer_id,
            'name': gift.offer.name,
            'type': 'bogo',
            'main_product': gift.offer.main_product.title,
            'gifts': [],
            'discount': Decimal('0')
        })
        entry['gifts'].append({
            'product': gift.product.title,
            'quantity': gift.quantity,
            'value': str(gift.original_total)
        })
        entry['discount'] += gift.original_total

    for entry in applied.values():
        entry['discount'] = str(entry['discount'])

    total = max(subtotal - discount, Decimal('0'))
    return {
        'subtotal': subtotal,
        'discount': discount,
        'total': total,
        'applied': list(applied.values()),
        'gifts': gifts,
        'auto_free_items': auto_free_items,
    }