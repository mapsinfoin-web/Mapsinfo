import uuid
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
import random
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django import forms
from django.urls import reverse
from django.utils import timezone
from urllib.parse import quote
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from .models import Product
from django.db.models import Q
from django.http import JsonResponse

from .forms import CustomRegistrationForm
from .models import (
    Cart, CartGift, CartItem, Category, ContactInquiry, Order, OrderItem, PaymentSettings, Product, Wishlist
)
from .offers import (
    add_gift, attach_offers, auto_fill_single_gift, calculate as calculate_offers, eligible_gifts,
    gift_slots_left, live_offers, offer_by_main, sync_gifts,
)


class OutOfStock(Exception):
    """Raised inside checkout when a product can't cover the quantity ordered."""


# ---------------------------------------------------------------------------
# STOREFRONT
# ---------------------------------------------------------------------------

def all_products(request):
    # Only fetch active products with prefetched relations for instant loading
    all_active = list(Product.objects.filter(is_active=True).select_related('category').prefetch_related('colors', 'sub_categories', 'category__subcategories').order_by('-created'))
    # 4 newest active products for Latest Arrivals
    recent_products = all_active[:4]
    recent_ids = {p.pk for p in recent_products}

    # Don't duplicate the 4 recent items in "Shop All Collection" if more products exist
    if len(all_active) > len(recent_ids):
        product_list = [p for p in all_active if p.pk not in recent_ids]
    else:
        product_list = all_active
    paginator = Paginator(product_list, 20) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Root categories for filter tabs (Earrings, Necklaces, Rings, Bracelets)
    categories = list(Category.objects.filter(parent__isnull=True).order_by('order', 'id'))

    # Offer badges ("Buy 1 Get 1 Free") for every card on the page
    offers = live_offers()
    attach_offers(page_obj, offers)
    attach_offers(recent_products, offers)

    # IDs of products the logged-in user has hearted (used to paint the hearts + header badge)
    user_wishlist = []
    if request.user.is_authenticated:
        user_wishlist = list(Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True))

    color_filters = _get_collection_color_filters(all_active)
    style_filters = _get_collection_style_filters(None, all_active)
    price_summary = _get_price_ranges(all_active)

    return render(request, 'store/index.html', {
        'page_obj': page_obj,
        'categories': categories,
        'recent_products': recent_products,
        'color_filters': color_filters,
        'style_filters': style_filters,
        'price_summary': price_summary,
        'user_wishlist': user_wishlist,
    })

def home(request):
    recent_products = attach_offers(list(Product.objects.filter(is_active=True).order_by('-created')[:4]))
    return render(request, 'store/home.html', {
        'recent_products': recent_products,

    })

# Trust words shown on every product page.
# The first three are shown on EVERY product. Each product also gets a few extra words picked
# from the pool below. The pick is "random" but fixed per product (it does not change on refresh).
# Edit the wording here whenever you like: (font-awesome icon, text)
TRUST_CORE = [
    ('fa-gem', 'Best Quality'),
    ('fa-shield-halved', 'Quality Assurance'),
    ('fa-tags', 'Best Price'),
]
TRUST_POOL = [
    ('fa-wand-magic-sparkles', 'Premium Finish'),
    ('fa-hand-holding-heart', 'Handpicked Design'),
    ('fa-lock', 'Secure Payment'),
    ('fa-gift', 'Gift Ready'),
    ('fa-heart', 'Customer Favourite'),
    ('fa-box-open', 'Carefully Packed'),
    ('fa-ring', 'Elegant Design'),
    ('fa-sun', 'Everyday Wear'),
    ('fa-circle-check', 'Durable Finish'),
    ('fa-fire', 'Trending Now'),
    ('fa-handshake', 'Trusted Seller'),
    ('fa-hourglass-half', 'Made to Last'),
]


def _trust_words(product, extra=3):
    """The 3 core words + `extra` more picked from the pool; the same words for the same product every time."""
    picks = random.Random(product.pk).sample(TRUST_POOL, extra)
    return TRUST_CORE + picks


def product_detail(request, pk):
    # Prevents users from accessing hidden products via direct URL links
    product = get_object_or_404(Product, pk=pk, is_active=True)
    attach_offers([product])
    # product.offer / offer: the live offer for this product (or None) - explain it on the page
    gift_choices = eligible_gifts(product.offer) if product.offer else []

    # Check if a specific colour was requested via ?color=
    requested_color = request.GET.get('color', '').strip()
    selected_color_obj = None
    colors = product.available_colors
    if requested_color and colors:
        for c in colors:
            if c.name.lower() == requested_color.lower():
                selected_color_obj = c
                break
    # If no ?color= query parameter was provided in the URL, selected_color_obj remains None
    # so that the product's primary/main image (product.image) is displayed by default.

    return render(request, 'store/product_detail.html', {
        'product': product,
        'offer': product.offer,
        'gift_choices': gift_choices,   # free gifts the customer can pick (active + in stock)
        'trust_words': _trust_words(product),   # [(icon, text), ...] shown under the price
        'selected_color_obj': selected_color_obj,
    })
# ---------------------------------------------------------------------------
# CART HELPERS
# ---------------------------------------------------------------------------

def _cart_id(request):
    """
    Return this visitor's active cart id and remember it in the session.
    """
    cart_id = request.session.get('cart_id')
    if not cart_id:
        if request.session.session_key:
            cart_id = request.session.session_key
        else:
            cart_id = uuid.uuid4().hex
        request.session['cart_id'] = cart_id
    return cart_id


def _sync_cart_user(request, cart):
    """Sync authenticated user and latest customer details to cart for admin follow-ups."""
    if not cart:
        return
    changed = False
    if request.user.is_authenticated:
        if cart.user_id != request.user.id:
            cart.user = request.user
            changed = True
        full_name = request.user.get_full_name() or request.user.first_name or request.user.username
        if not cart.customer_name and full_name:
            cart.customer_name = full_name
            changed = True
        if not cart.customer_email and request.user.email:
            cart.customer_email = request.user.email
            changed = True
        if not cart.customer_phone:
            latest_order = Order.objects.filter(user=request.user).exclude(mobile_number='').order_by('-date_ordered').first()
            if latest_order and latest_order.mobile_number:
                cart.customer_phone = latest_order.mobile_number
                changed = True
    if changed:
        cart.save(update_fields=['user', 'customer_name', 'customer_email', 'customer_phone', 'updated_at'])


def _get_cart(request, create=False):
    cart_id = _cart_id(request)
    cart = Cart.objects.filter(cart_id=cart_id, is_purchased=False).first()
    if cart is None and request.user.is_authenticated:
        user_cart = Cart.objects.filter(user=request.user, is_purchased=False).first()
        if user_cart:
            cart = user_cart
            request.session['cart_id'] = cart.cart_id
    if cart is None and create:
        cart = Cart.objects.create(cart_id=cart_id)
    if cart:
        _sync_cart_user(request, cart)
    return cart


def _stock_problems(cart_items):
    """Return a list of human-readable problems (empty list = everything is available)."""
    problems = []
    for item in cart_items:
        product = item.product
        if not product.is_active:
            problems.append(f"{product.title} is no longer available. Please remove it from your cart.")
        elif product.stock <= 0:
            problems.append(f"{product.title} is out of stock. Please remove it from your cart.")
        elif item.quantity > product.stock:
            problems.append(f"Only {product.stock} of {product.title} left. Please reduce the quantity.")
    return problems


# ---------------------------------------------------------------------------
# CART VIEWS
# ---------------------------------------------------------------------------


def _cart_url():
    """Cart page, scrolled to the free-gift box."""
    return reverse('store:cart_detail') + '#gifts'


def _handle_gift_after_add(request, cart, product):
    """
    Called right after a product was put in the cart. If it has a free-gift offer:
      * ?gift=<id> / POST gift=<id> (chosen on the product page) -> add that gift,
      * only one gift possible -> add it automatically,
      * several gifts possible -> tell the customer to pick one.
    Returns True when the customer should land on the cart's gift box.
    """
    offer = offer_by_main(live_offers()).get(product.pk)
    if offer is None:
        return False

    wanted = request.POST.get('gift') or request.GET.get('gift') or ''
    if wanted.isdigit():
        ok, text = add_gift(cart, offer, int(wanted))
        (messages.success if ok else messages.error)(request, text)
        return True

    added = auto_fill_single_gift(cart, offer)
    if added:
        messages.success(request, f"Free gift added: {added.title}. You pay only for {product.title}.")
    elif eligible_gifts(offer) and gift_slots_left(cart, offer) > 0:
        messages.info(request, f"Choose your FREE gift with your {product.title} below.")
    return True


def add_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

    # Save selected color variant in session
    selected_color = (request.POST.get('selected_color') or request.GET.get('selected_color') or '').strip()
    if selected_color:
        cart_colors = request.session.get('cart_colors', {})
        cart_colors[str(product.id)] = selected_color
        request.session['cart_colors'] = cart_colors
        request.session.modified = True

    if not product.in_stock:
        if is_ajax:
            return JsonResponse({'status': 'error', 'error': f"Sorry, {product.title} is out of stock."}, status=400)
        messages.error(request, f"Sorry, {product.title} is out of stock.")
        return redirect('store:product_detail', pk=product.pk)

    cart = _get_cart(request, create=True)
    cart_item = CartItem.objects.filter(product=product, cart=cart).first()
    current_qty = cart_item.quantity if cart_item else 0

    if current_qty + 1 > product.stock:
        if is_ajax:
            return JsonResponse({'status': 'error', 'error': f"Only {product.stock} of {product.title} available."}, status=400)
        messages.error(request, f"Only {product.stock} of {product.title} available. "
                                f"You already have {current_qty} in your cart.")
        return redirect('store:product_detail', pk=product.pk)

    if cart_item:
        cart_item.quantity += 1
        cart_item.save()
    else:
        CartItem.objects.create(product=product, cart=cart, quantity=1)

    went_to_gifts = _handle_gift_after_add(request, cart, product)

    if is_ajax:
        total_items = sum(CartItem.objects.filter(cart=cart).values_list('quantity', flat=True))
        return JsonResponse({
            'status': 'success',
            'cart_count': total_items,
            'message': f"{product.title} added to cart!"
        })

    if went_to_gifts:
        return redirect(_cart_url())
    return redirect('store:cart_detail')


def _priced_cart(cart, request=None):
    """Drop invalid gifts, then price the cart. Returns (cart_items, pricing, notes)."""
    notes = sync_gifts(cart)
    cart_items = CartItem.objects.filter(cart=cart, is_active=True).select_related('product')
    if request:
        cart_colors = request.session.get('cart_colors', {})
        for item in cart_items:
            item.selected_color = cart_colors.get(str(item.product_id), '')
    gifts = cart.gifts.select_related('product', 'offer__main_product')
    return cart_items, calculate_offers(cart_items, gifts), notes


def cart_detail(request):
    pricing = {'subtotal': 0, 'discount': 0, 'total': 0, 'applied': [], 'gifts': []}
    cart_items = None
    gifts_pending = False
    gift_anchor_id = None
    cart = _get_cart(request)
    if cart:
        cart_items, pricing, notes = _priced_cart(cart, request)
        cart_colors = request.session.get('cart_colors', {})
        for item in cart_items:
            item.selected_color = cart_colors.get(str(item.product_id), '')
        for note in notes:
            messages.warning(request, note)
        for problem in _stock_problems(cart_items):
            messages.warning(request, problem)
        with_offer = [i for i in cart_items if i.offer]
        waiting = [i for i in with_offer if i.gift_slots_left > 0 and i.gift_choices]
        gifts_pending = bool(waiting)
        first = (waiting or with_offer or [None])[0]
        gift_anchor_id = first.product_id if first else None

    return render(request, 'store/cart.html', {
        'cart_items': cart_items,
        'gifts': pricing['gifts'],
        'subtotal': pricing['subtotal'],
        'savings': pricing['discount'],
        'total': pricing['total'],
        'applied_offers': pricing['applied'],
        'gifts_pending': gifts_pending,          # True -> show the "free gift waiting" banner
        'gift_anchor_id': gift_anchor_id,        # the gift box the page scrolls to
    })


@require_POST
def choose_gift(request):
    """The customer picks a free gift for a main product in their cart. Everything is re-checked on the server."""
    cart = _get_cart(request)
    try:
        main_id = int(request.POST.get('main_product_id', ''))
        gift_id = int(request.POST.get('gift_product_id', ''))
    except ValueError:
        return redirect('store:cart_detail')
    if not cart:
        return redirect('store:cart_detail')

    sync_gifts(cart)

    # The offer comes from the server (via the main product), never from the request
    offer = offer_by_main(live_offers()).get(main_id)
    if offer is None:
        messages.error(request, "That free gift offer isn't available.")
        return redirect('store:cart_detail')

    ok, text = add_gift(cart, offer, gift_id)
    (messages.success if ok else messages.error)(request, text)
    return redirect('store:cart_detail')


@require_POST
def remove_gift(request, gift_id):
    cart = _get_cart(request)
    if cart:
        CartGift.objects.filter(pk=gift_id, cart=cart).delete()
    return redirect('store:cart_detail')


def remove_cart(request, product_id):
    cart = _get_cart(request)
    product = get_object_or_404(Product, id=product_id)
    if cart:
        cart_item = CartItem.objects.filter(product=product, cart=cart).first()
        if cart_item:
            if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
            else:
                cart_item.delete()
    return redirect('store:cart_detail')


def remove_cart_item(request, product_id):
    cart = _get_cart(request)
    product = get_object_or_404(Product, id=product_id)
    if cart:
        CartItem.objects.filter(product=product, cart=cart).delete()
    return redirect('store:cart_detail')


@require_POST
def buy_now(request, pk):
    """Put the product in the cart. Products with a free-gift offer go to the cart so the gift can be picked."""
    product = get_object_or_404(Product, pk=pk, is_active=True)

    # Save selected color variant in session
    selected_color = (request.POST.get('selected_color') or request.GET.get('selected_color') or '').strip()
    if selected_color:
        cart_colors = request.session.get('cart_colors', {})
        cart_colors[str(product.id)] = selected_color
        request.session['cart_colors'] = cart_colors
        request.session.modified = True

    if not product.in_stock:
        messages.error(request, f"Sorry, {product.title} is out of stock.")
        return redirect('store:product_detail', pk=product.pk)

    cart = _get_cart(request, create=True)
    if not CartItem.objects.filter(product=product, cart=cart).exists():
        CartItem.objects.create(product=product, cart=cart, quantity=1)

    went_to_gifts = _handle_gift_after_add(request, cart, product)
    if went_to_gifts and not request.POST.get('gift'):
        return redirect(_cart_url())      # no gift chosen yet: let the customer pick one in the cart
    return redirect('store:checkout')      # gift already chosen on the product page (or no offer)


# ---------------------------------------------------------------------------
# AUTHENTICATION VIEWS
# ---------------------------------------------------------------------------

def register_user(request):
    if request.method == 'POST':
        form = CustomRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Two login systems are installed (Django + allauth), so say which one to use
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            cart = _get_cart(request)
            if cart:
                phone = form.cleaned_data.get('phone_number')
                if phone and not cart.customer_phone:
                    cart.customer_phone = phone
                    cart.save(update_fields=['customer_phone'])
                _sync_cart_user(request, cart)
            return redirect('store:all_products')
    else:
        form = CustomRegistrationForm()
    return render(request, 'store/register.html', {'form': form})


def login_user(request):
    next_url = request.POST.get('next') or request.GET.get('next') or ''

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            cart = _get_cart(request)
            if cart:
                _sync_cart_user(request, cart)
            # Send the customer back to where they were going (e.g. checkout)
            if next_url and url_has_allowed_host_and_scheme(
                    next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('store:all_products')
    else:
        form = AuthenticationForm()
    return render(request, 'store/login.html', {'form': form, 'next': next_url})


def logout_user(request):
    logout(request)
    return redirect('store:login_user')


# ---------------------------------------------------------------------------
# CHECKOUT VIEWS
# ---------------------------------------------------------------------------

@login_required(login_url='store:login_user')
def checkout(request):
    cart = _get_cart(request)
    if not cart or not CartItem.objects.filter(cart=cart, is_active=True).exists():
        messages.info(request, "Your cart is empty.")
        return redirect('store:all_products')

    # Re-validate offers and gifts on the server on EVERY request (dates, switches, stock, quantities)
    cart_items, pricing, notes = _priced_cart(cart, request)
    cart_colors = request.session.get('cart_colors', {})
    for item in cart_items:
        item.selected_color = cart_colors.get(str(item.product_id), '')
    for note in notes:
        messages.warning(request, note)

    context = {
        'cart_items': cart_items,
        'gifts': pricing['gifts'],
        'subtotal': pricing['subtotal'],
        'savings': pricing['discount'],
        'total': pricing['total'],
        'applied_offers': pricing['applied'],
    }

    if request.method == 'POST':
        full_name = (request.POST.get('full_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        mobile_number = (request.POST.get('mobile_number') or '').strip()
        shipping_address = (request.POST.get('shipping_address') or '').strip()
        city = (request.POST.get('city') or '').strip()
        postal_code = (request.POST.get('postal_code') or '').strip()
        payment_method = 'PAYTM'   # the only payment method: Paytm QR (never trust the browser for this)

        context['form_data'] = request.POST

        # Save customer contact info immediately to cart for admin follow-up
        if cart:
            if full_name:
                cart.customer_name = full_name
            if email:
                cart.customer_email = email
            if mobile_number:
                cart.customer_phone = mobile_number
            cart.save(update_fields=['customer_name', 'customer_email', 'customer_phone', 'updated_at'])

        # 1. Validate the form
        required = [full_name, email, mobile_number, shipping_address, city, postal_code]
        if not all(required):
            messages.error(request, "Please fill in all the delivery details.")
            return render(request, 'store/checkout.html', context)

        # 2. Quick stock check so the customer gets a clear message
        problems = _stock_problems(cart_items)
        if problems:
            for problem in problems:
                messages.error(request, problem)
            return redirect('store:cart_detail')

        # 3. If an offer or price changed since the page was shown, never charge a different amount
        #    silently: show the new total and let the customer confirm again.
        try:
            expected_total = Decimal(request.POST.get('expected_total', ''))
        except InvalidOperation:
            expected_total = None
        if expected_total is not None and expected_total != pricing['total']:
            messages.warning(request, "An offer or price changed, so your total was updated. "
                                      "Please review it and place the order again.")
            return render(request, 'store/checkout.html', context)

        # 4. Create the order and take the stock (paid items AND free gifts) in ONE transaction.
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    user=request.user,
                    full_name=full_name,
                    email=email,
                    mobile_number=mobile_number,
                    shipping_address=shipping_address,
                    city=city,
                    postal_code=postal_code,
                    amount_paid=pricing['total'],          # gifts are free: only paid items are charged
                    discount_amount=pricing['discount'],
                    offers_applied=pricing['applied'],
                    payment_method=payment_method,
                )

                for item in cart_items:
                    updated = Product.objects.filter(
                        pk=item.product_id, stock__gte=item.quantity
                    ).update(stock=F('stock') - item.quantity)
                    if not updated:
                        raise OutOfStock(item.product.title)
                    OrderItem.objects.create(order=order, product=item.product,
                                             color=getattr(item, 'selected_color', '') or '',
                                             price=getattr(item, 'unit_price', item.product.price),
                                             quantity=item.quantity)

                # Free gifts: a separate line at Rs.0, linked to the offer, and they leave the shelf too
                for gift in pricing['gifts']:
                    updated = Product.objects.filter(
                        pk=gift.product_id, stock__gte=gift.quantity
                    ).update(stock=F('stock') - gift.quantity)
                    if not updated:
                        raise OutOfStock(gift.product.title)
                    OrderItem.objects.create(order=order, product=gift.product, price=0, quantity=gift.quantity,
                                             is_free_gift=True, bogo_offer_id=gift.offer_id)
        except OutOfStock as exc:
            messages.error(request, f"Sorry, {exc} just sold out. Please update your cart.")
            return redirect('store:cart_detail')

        # Mark cart as purchased and link to order for complete history
        cart.is_purchased = True
        cart.order = order
        if full_name:
            cart.customer_name = full_name
        if email:
            cart.customer_email = email
        if mobile_number:
            cart.customer_phone = mobile_number
        cart.save()
        cart_items.update(is_active=False)
        request.session.pop('cart_id', None)
        request.session['last_order_id'] = order.id

        # Next: the Paytm QR page, where the customer pays and uploads the screenshot
        return redirect('store:order_payment', order_id=order.id)

    # GET: warn early if something in the cart is no longer available
    for problem in _stock_problems(cart_items):
        messages.warning(request, problem)

    if request.user.is_authenticated and 'form_data' not in context:
        initial_phone = ''
        if hasattr(request.user, 'profile') and request.user.profile.phone_number:
            initial_phone = request.user.profile.phone_number
        elif cart and cart.customer_phone:
            initial_phone = cart.customer_phone

        full_name = f"{request.user.first_name} {request.user.last_name}".strip()
        context['form_data'] = {
            'full_name': full_name or request.user.username,
            'email': request.user.email,
            'mobile_number': initial_phone,
        }

    return render(request, 'store/checkout.html', context)


class PaymentScreenshotForm(forms.Form):
    screenshot = forms.ImageField(error_messages={
        'invalid_image': 'Please upload a photo or screenshot (JPG, PNG or WEBP).',
        'required': 'Please choose your payment screenshot first.'})

    def clean_screenshot(self):
        image = self.cleaned_data['screenshot']
        # Vercel refuses request bodies over ~4.5 MB before Django even sees them, so stay below that
        if image.size > 4 * 1024 * 1024:
            raise forms.ValidationError('The screenshot is too big. Please upload an image under 4 MB.')
        return image


def _whatsapp_link(request, order, settings_obj=None):
    """wa.me link that opens WhatsApp to the vendor with the full order details and the screenshot link."""
    number = PaymentSettings.vendor_number()
    lines = [
        f"*New order #{order.pk}*",
        f"Name: {order.full_name}",
        f"Phone: {order.mobile_number}",
        f"Address: {order.shipping_address}, {order.city} - {order.postal_code}",
        "",
        "*Products purchased:*",
    ]
    cart_colors = request.session.get('cart_colors', {}) if request else {}
    for item in order.items.select_related('product'):
        color_val = getattr(item, 'color', '') or cart_colors.get(str(item.product_id), '')
        color_tag = f" [Colour: {color_val}]" if color_val else ""
        if item.is_free_gift:
            lines.append(f"- {item.quantity} x {item.product.title}{color_tag} (FREE GIFT)")
        else:
            lines.append(f"- {item.quantity} x {item.product.title}{color_tag} - Rs.{item.price * item.quantity}")
    lines += ["", f"*Amount paid (Paytm): Rs.{order.amount_paid}*"]
    if order.payment_screenshot:
        lines.append(f"Payment screenshot: {request.build_absolute_uri(order.payment_screenshot.url)}")
    return f"https://wa.me/{number}?text={quote(chr(10).join(lines))}"


@login_required(login_url='store:login_user')
def order_payment(request, order_id):
    """Pay with the Paytm QR, upload the payment screenshot, share the order with the vendor on WhatsApp."""
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    shop = PaymentSettings.get()
    form = PaymentScreenshotForm()

    if request.method == 'POST':
        if order.status == 'CANCELLED' or order.is_paid:
            messages.info(request, "This order no longer needs a payment screenshot.")
            return redirect('store:order_payment', order_id=order.pk)
        form = PaymentScreenshotForm(request.POST, request.FILES)
        if form.is_valid():
            order.payment_screenshot = form.cleaned_data['screenshot']
            order.payment_submitted_at = timezone.now()
            order.save(update_fields=['payment_screenshot', 'payment_submitted_at'])
            messages.success(request, "Screenshot uploaded. Now tap the green button to share your order with us on WhatsApp.")
            return redirect('store:order_payment', order_id=order.pk)

    upi_id = shop.get_upi_id() if shop else 'maps536969@sbi'
    payee_name = (shop.payee_name if shop and shop.payee_name else 'MAPSKART').strip()
    upi_intent_url = f"upi://pay?pa={upi_id}&pn={quote(payee_name)}&am={order.amount_paid}&cu=INR&tn={quote(f'Order_{order.pk}')}"

    return render(request, 'store/order_payment.html', {
        'order': order,
        'items': order.items.select_related('product'),
        'shop': shop,
        'form': form,
        'upi_id': upi_id,
        'upi_intent_url': upi_intent_url,
        'whatsapp_url': _whatsapp_link(request, order, shop) if order.payment_screenshot else '',
    })


def checkout_success(request):
    order = None
    order_id = request.session.get('last_order_id')
    if order_id and request.user.is_authenticated:
        order = Order.objects.filter(pk=order_id, user=request.user).first()
    return render(request, 'store/checkout_success.html', {'order': order})


# ---------------------------------------------------------------------------
# CUSTOMER DASHBOARD
# ---------------------------------------------------------------------------

@login_required(login_url='store:login_user')
def my_orders(request):
    orders = (Order.objects.filter(user=request.user)
              .prefetch_related('items__product')
              .order_by('-date_ordered'))
    return render(request, 'store/my_orders.html', {'orders': orders})


# ---------------------------------------------------------------------------
# COLOR FILTER UTILITIES
# ---------------------------------------------------------------------------

COLOR_HEX_MAP = {
    'blue': {'name': 'Blue', 'hex': '#2563EB'},
    'pink': {'name': 'Pink', 'hex': '#EC4899'},
    'green': {'name': 'Green', 'hex': '#059669'},
    'purple': {'name': 'Purple', 'hex': '#9333EA'},
    'crystal': {'name': 'Crystal', 'hex': '#CBD5E1'},
    'white': {'name': 'White', 'hex': '#F1F5F9'},
    'yellow': {'name': 'Yellow', 'hex': '#EAB308'},
    'gold': {'name': 'Gold', 'hex': '#D4AF37'},
    'black': {'name': 'Black', 'hex': '#1E293B'},
    'multicolour': {'name': 'Multicolour', 'hex': '#8B5CF6'},
    'ruby': {'name': 'Ruby', 'hex': '#E11D48'},
    'silver': {'name': 'Silver', 'hex': '#94A3B8'},
}

def _get_collection_color_filters(products):
    """Computes distinct colors present in the given products with count and hex."""
    counts = {}
    for p in products:
        for tag in p.color_tags:
            counts[tag] = counts.get(tag, 0) + 1

    color_filters = []
    for slug, count in counts.items():
        info = COLOR_HEX_MAP.get(slug, {'name': slug.capitalize(), 'hex': '#64748B'})
        color_filters.append({
            'slug': slug,
            'name': info['name'],
            'hex': info['hex'],
            'count': count,
        })
    color_filters.sort(key=lambda x: (-x['count'], x['name']))
    return color_filters


def _get_collection_style_filters(category, products):
    """Computes active subcategories/styles under the given category with product counts."""
    if not category:
        subcats = list(Category.objects.filter(parent__isnull=False).select_related('parent').order_by('order', 'name'))
    else:
        target_cat = category.parent if category.parent else category
        subcats = list(target_cat.subcategories.all().order_by('order', 'name'))

    style_filters = []
    for sc in subcats:
        c = sum(1 for p in products if sc.slug.lower() in p.style_tags)
        style_filters.append({
            'id': sc.id,
            'name': sc.name,
            'slug': sc.slug.lower(),
            'count': c,
            'parent_slug': sc.parent.slug if sc.parent else '',
        })
    return style_filters


def _get_price_ranges(products):
    """Counts how many products fall into standard price brackets."""
    counts = {
        'under-250': 0,
        '250-499': 0,
        '500-999': 0,
        '1000-plus': 0,
    }
    for p in products:
        try:
            price = float(p.price)
            if price < 250:
                counts['under-250'] += 1
            elif 250 <= price < 500:
                counts['250-499'] += 1
            elif 500 <= price < 1000:
                counts['500-999'] += 1
            else:
                counts['1000-plus'] += 1
        except Exception:
            pass
    return counts


# ---------------------------------------------------------------------------
# COLLECTIONS
# ---------------------------------------------------------------------------

def collections(request):
    main_categories = list(Category.objects.filter(parent__isnull=True).prefetch_related('subcategories').order_by('order', 'id'))
    
    active_cat_slug = request.GET.get('cat', '').strip().lower()
    active_sub_slug = request.GET.get('sub', '').strip().lower()

    # Determine active main category
    active_main_cat = None
    if active_cat_slug:
        active_main_cat = next((c for c in main_categories if c.slug.lower() == active_cat_slug), None)
    
    # Base products for category context
    base_products_qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('colors', 'sub_categories', 'category__subcategories').distinct().order_by('-created')
    if active_main_cat:
        base_products_qs = base_products_qs.filter(Q(category=active_main_cat) | Q(category__parent=active_main_cat) | Q(sub_categories__parent=active_main_cat))
    
    base_products = list(base_products_qs)
    total_count = len(base_products)

    # Subcategories to display at starting of page
    if active_main_cat:
        subcategories = list(active_main_cat.subcategories.all().order_by('order', 'id'))
    else:
        # Show all subcategories across categories, ordered nicely
        subcategories = list(Category.objects.filter(parent__isnull=False).select_related('parent').order_by('parent__order', 'order', 'name'))

    # Precompute counts for subcategories based on base_products
    for sub in subcategories:
        sub.product_count = sum(1 for p in base_products if sub.slug.lower() in p.style_tags or (p.category and p.category.slug.lower() == sub.slug.lower()))

    if active_sub_slug:
        products_list = [p for p in base_products if active_sub_slug in p.style_tags or (p.category and p.category.slug.lower() == active_sub_slug)]
    else:
        products_list = base_products

    products = attach_offers(products_list)
    color_filters = _get_collection_color_filters(products)
    price_summary = _get_price_ranges(products)

    return render(request, 'store/collections.html', {
        'categories': main_categories,
        'active_main_cat': active_main_cat,
        'active_cat_slug': active_cat_slug,
        'active_sub_slug': active_sub_slug,
        'subcategories': subcategories,
        'total_count': total_count,
        'products': products,
        'color_filters': color_filters,
        'price_summary': price_summary,
    })


def collection_detail(request, slug):
    category = Category.objects.filter(slug__iexact=slug).first() or get_object_or_404(Category, slug=slug)
    # Filter out hidden products from category pages
    is_subcollection = (category.parent is not None or category.slug == 'layered-necklaces')
    parent_category = category.parent if category.parent else (Category.objects.filter(slug='necklaces').first() if is_subcollection else None)
    main_cat = parent_category if is_subcollection else category

    # Subcategories of this main category
    subcategories = list(main_cat.subcategories.all().order_by('order', 'id'))
    
    active_sub = request.GET.get('sub', '').strip().lower()
    if is_subcollection and not active_sub:
        active_sub = category.slug

    # Fetch all products under main category
    all_main_products_qs = Product.objects.filter(
        Q(category=main_cat) | Q(category__parent=main_cat) | Q(sub_categories__parent=main_cat),
        is_active=True
    ).select_related('category').prefetch_related('colors', 'sub_categories', 'category__subcategories').distinct().order_by('-created')
    all_main_products = list(all_main_products_qs)
    total_main_count = len(all_main_products)

    # Compute count for each subcategory
    for sub in subcategories:
        sub.product_count = sum(1 for p in all_main_products if sub.slug.lower() in p.style_tags)

    if is_subcollection:
        products = attach_offers([p for p in all_main_products if (p.category == category or category in p.sub_categories.all() or category.slug.lower() in p.style_tags)])
    elif active_sub:
        products = attach_offers([p for p in all_main_products if active_sub in p.style_tags])
    else:
        products = attach_offers(all_main_products)

    color_filters = _get_collection_color_filters(products)
    style_filters = _get_collection_style_filters(category, products)
    price_summary = _get_price_ranges(products)
    selected_color = request.GET.get('color', '').strip().lower()

    return render(request, 'store/collection_detail.html', {
        'category': category,
        'main_cat': main_cat,
        'subcategories': subcategories,
        'is_subcollection': is_subcollection,
        'parent_category': parent_category,
        'total_main_count': total_main_count,
        'active_sub': active_sub,
        'products': products,
        'color_filters': color_filters,
        'style_filters': style_filters,
        'price_summary': price_summary,
        'selected_color': selected_color,
    })


# ---------------------------------------------------------------------------
# STATIC PAGES
# ---------------------------------------------------------------------------

def about(request):
    return render(request, 'store/about.html')


def contact(request):
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        subject = (request.POST.get('subject') or '').strip()
        message = (request.POST.get('message') or '').strip()

        if not (name and email and subject and message):
            messages.error(request, "Please fill in all the fields.")
            return redirect('store:contact')

        ContactInquiry.objects.create(name=name, email=email, subject=subject, message=message)
        messages.success(request, "Thank you. Your inquiry has been forwarded to our atelier.")
        return redirect('store:contact')

    return render(request, 'store/contact.html')

def search_products(request):
    query = request.GET.get('q', '').strip()

    if query:
        # Filter for active products matching the query in title or description
        product_list = Product.objects.filter(
            Q(title__icontains=query) | Q(description__icontains=query),
            is_active=True
        ).select_related('category').prefetch_related('colors', 'sub_categories', 'category__subcategories').order_by('-id')
    else:
        product_list = Product.objects.none()

    paginator = Paginator(product_list, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    attach_offers(page_obj)

    user_wishlist = []
    if request.user.is_authenticated:
        user_wishlist = list(Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True))

    categories = list(Category.objects.filter(parent__isnull=True).order_by('order', 'id'))
    color_filters = _get_collection_color_filters(product_list)
    style_filters = _get_collection_style_filters(None, product_list)
    price_summary = _get_price_ranges(product_list)
    return render(request, 'store/search.html', {
        'page_obj': page_obj,
        'categories': categories,
        'query': query,
        'color_filters': color_filters,
        'style_filters': style_filters,
        'price_summary': price_summary,
        'user_wishlist': user_wishlist,
    })

def sale_products(request):
    all_active = Product.objects.filter(is_active=True).select_related('category')
    # Filter products where MRP is greater than price (on sale)
    sale_list = all_active.filter(
        Q(mrp__isnull=False) & Q(mrp__gt=F('price'))
    ).order_by('-id')

    if not sale_list.exists():
        sale_list = all_active.order_by('-id')

    # Category filter support
    category_slug = request.GET.get('category', '').strip()
    selected_category = None
    if category_slug:
        selected_category = Category.objects.filter(slug__iexact=category_slug).first()
        if selected_category:
            sale_list = sale_list.filter(category=selected_category)

    paginator = Paginator(sale_list, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    attach_offers(page_obj)

    user_wishlist = []
    if request.user.is_authenticated:
        user_wishlist = list(Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True))

    categories = list(Category.objects.all())
    return render(request, 'store/sale.html', {
        'page_obj': page_obj,
        'categories': categories,
        'selected_category': selected_category,
        'user_wishlist': user_wishlist,
    })


@login_required(login_url='store:login_user')
def wishlist(request):
    # Fetch all wishlist records for this user and pull in the product data
    wishlist_records = Wishlist.objects.filter(user=request.user).select_related('product', 'product__category')

    return render(request, 'store/wishlist.html', {
        'wishlist_records': wishlist_records,
    })


def toggle_wishlist(request, product_id):
    # Used by the heart buttons (AJAX). Always answers with JSON.
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'login_required'}, status=401)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    product = get_object_or_404(Product, id=product_id)
    # get_or_create looks for the like. If it doesn't exist, it creates it.
    w_item, created = Wishlist.objects.get_or_create(user=request.user, product=product)

    if not created:
        # It already existed, so the user is "un-liking" it
        w_item.delete()
        return JsonResponse({'status': 'removed'})

    return JsonResponse({'status': 'added'})


# ---------------------------------------------------------------------------
# ERROR PAGES (400 / 403 / 404 / 500)
# Shown with the real status code, then the page sends the visitor to the home page.
# These only run when DEBUG = False.
# ---------------------------------------------------------------------------

def _error_page(request, status):
    try:
        return render(request, 'store/error.html', {'status': status}, status=status)
    except Exception:
        from django.http import HttpResponse
        return HttpResponse(
            f"<!DOCTYPE html><html><head><title>Error {status}</title><style>body{{font-family:sans-serif;text-align:center;padding:60px 20px;color:#132639}}h1{{font-size:36px;margin-bottom:12px}}p{{color:#52637a;font-size:16px}}a{{display:inline-block;margin-top:20px;padding:12px 24px;background:#1F3A66;color:#fff;text-decoration:none;border-radius:999px}}</style></head><body><h1>Something went wrong ({status})</h1><p>We are temporarily experiencing connection issues. Please refresh or try again in a moment.</p><a href='/'>Return to Home</a></body></html>",
            status=status
        )


def bad_request(request, exception=None):
    return _error_page(request, 400)


def permission_denied(request, exception=None):
    return _error_page(request, 403)


def page_not_found(request, exception=None):
    return _error_page(request, 404)


def server_error(request):
    return _error_page(request, 500)

@require_POST
def save_cart_contact(request):
    """
    Real-time AJAX endpoint called on checkout page when user fills in contact details.
    Allows capturing customer name, email, and mobile number even if they abandon checkout.
    """
    cart = _get_cart(request, create=False)
    if not cart:
        return JsonResponse({'status': 'no_cart'})

    full_name = (request.POST.get('full_name') or '').strip()
    email = (request.POST.get('email') or '').strip()
    mobile_number = (request.POST.get('mobile_number') or '').strip()

    changed = False
    if full_name and cart.customer_name != full_name:
        cart.customer_name = full_name
        changed = True
    if email and cart.customer_email != email:
        cart.customer_email = email
        changed = True
    if mobile_number and cart.customer_phone != mobile_number:
        cart.customer_phone = mobile_number
        changed = True
    if request.user.is_authenticated and not cart.user:
        cart.user = request.user
        changed = True

    if changed:
        cart.save(update_fields=['customer_name', 'customer_email', 'customer_phone', 'user', 'updated_at'])

    return JsonResponse({'status': 'saved'})
