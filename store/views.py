from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from .models import Product
from django.db.models import Q
from django.http import JsonResponse

from .forms import CustomRegistrationForm
from .models import (
    Cart, CartItem, Category, ContactInquiry, Order, OrderItem, Product,Wishlist
)


class OutOfStock(Exception):
    """Raised inside checkout when a product can't cover the quantity ordered."""


# ---------------------------------------------------------------------------
# STOREFRONT
# ---------------------------------------------------------------------------

def all_products(request):
    # Only fetch active products
    product_list = Product.objects.filter(is_active=True)
    paginator = Paginator(product_list, 12) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Only show active products in Latest Arrivals
    recent_products = Product.objects.filter(is_active=True).order_by('-created')[:4]

    # ---> ADD THESE LINES THAT ARE MISSING <---
    user_wishlist = []
    if request.user.is_authenticated:
        user_wishlist = Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True)

    return render(request, 'store/index.html', {
        'page_obj': page_obj,
        'recent_products': recent_products,
        'user_wishlist': user_wishlist,
    })

def home(request):
    recent_products = Product.objects.filter(is_active=True).order_by('-created')[:4]
    return render(request, 'store/home.html', {
        'recent_products': recent_products,
    })

def product_detail(request, pk):
    # Prevents users from accessing hidden products via direct URL links
    product = get_object_or_404(Product, pk=pk, is_active=True)
    return render(request, 'store/product_detail.html', {'product': product})
# ---------------------------------------------------------------------------
# CART HELPERS
# ---------------------------------------------------------------------------

def _cart_id(request):
    """
    Return this visitor's cart id and remember it in the session.
    Django changes session_key when a user logs in, so we store our own
    'cart_id' value to keep the cart from disappearing at login.
    """
    cart_id = request.session.get('cart_id')
    if not cart_id:
        if not request.session.session_key:
            request.session.create()
        cart_id = request.session.session_key
        request.session['cart_id'] = cart_id
    return cart_id


def _get_cart(request, create=False):
    cart_id = _cart_id(request)
    cart = Cart.objects.filter(cart_id=cart_id).first()
    if cart is None and create:
        cart = Cart.objects.create(cart_id=cart_id)
    return cart


def _stock_problems(cart_items):
    """Return a list of human-readable problems (empty list = everything is available)."""
    problems = []
    for item in cart_items:
        product = item.product
        if product.stock <= 0:
            problems.append(f"{product.title} is out of stock. Please remove it from your cart.")
        elif item.quantity > product.stock:
            problems.append(f"Only {product.stock} of {product.title} left. Please reduce the quantity.")
    return problems


# ---------------------------------------------------------------------------
# CART VIEWS
# ---------------------------------------------------------------------------

def add_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if not product.in_stock:
        messages.error(request, f"Sorry, {product.title} is out of stock.")
        return redirect('store:product_detail', pk=product.pk)

    cart = _get_cart(request, create=True)
    cart_item = CartItem.objects.filter(product=product, cart=cart).first()
    current_qty = cart_item.quantity if cart_item else 0

    if current_qty + 1 > product.stock:
        messages.error(request, f"Only {product.stock} of {product.title} available. "
                                f"You already have {current_qty} in your cart.")
        return redirect('store:product_detail', pk=product.pk)

    if cart_item:
        cart_item.quantity += 1
        cart_item.save()
    else:
        CartItem.objects.create(product=product, cart=cart, quantity=1)

    return redirect('store:cart_detail')


def cart_detail(request):
    total = 0
    cart_items = None
    cart = _get_cart(request)
    if cart:
        cart_items = CartItem.objects.filter(cart=cart, is_active=True).select_related('product')
        for cart_item in cart_items:
            total += cart_item.product.price * cart_item.quantity
        for problem in _stock_problems(cart_items):
            messages.warning(request, problem)

    return render(request, 'store/cart.html', {
        'cart_items': cart_items,
        'total': total,
    })


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
    """Put the product in the cart (if it isn't already) and go straight to checkout."""
    product = get_object_or_404(Product, pk=pk)

    if not product.in_stock:
        messages.error(request, f"Sorry, {product.title} is out of stock.")
        return redirect('store:product_detail', pk=product.pk)

    cart = _get_cart(request, create=True)
    if not CartItem.objects.filter(product=product, cart=cart).exists():
        CartItem.objects.create(product=product, cart=cart, quantity=1)

    return redirect('store:checkout')


# ---------------------------------------------------------------------------
# AUTHENTICATION VIEWS
# ---------------------------------------------------------------------------

def register_user(request):
    if request.method == 'POST':
        form = CustomRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Automatically log the user in after registration
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
    cart_items = (CartItem.objects.filter(cart=cart, is_active=True).select_related('product')
                  if cart else CartItem.objects.none())

    # Nothing to buy -> back to the shop (prevents empty / Rs.0 orders)
    if not cart_items.exists():
        messages.info(request, "Your cart is empty.")
        return redirect('store:all_products')

    total = sum(item.product.price * item.quantity for item in cart_items)
    context = {'cart_items': cart_items, 'total': total}

    if request.method == 'POST':
        full_name = (request.POST.get('full_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        mobile_number = (request.POST.get('mobile_number') or '').strip()
        shipping_address = (request.POST.get('shipping_address') or '').strip()
        city = (request.POST.get('city') or '').strip()
        postal_code = (request.POST.get('postal_code') or '').strip()
        payment_method = request.POST.get('payment_method') or ''

        context['form_data'] = request.POST

        # 1. Validate the form
        required = [full_name, email, mobile_number, shipping_address, city, postal_code]
        if not all(required):
            messages.error(request, "Please fill in all the delivery details.")
            return render(request, 'store/checkout.html', context)

        if payment_method not in dict(Order.PAYMENT_CHOICES):
            messages.error(request, "Please choose a valid payment method.")
            return render(request, 'store/checkout.html', context)

        # 2. Quick stock check so the customer gets a clear message
        problems = _stock_problems(cart_items)
        if problems:
            for problem in problems:
                messages.error(request, problem)
            return redirect('store:cart_detail')

        # 3. Create the order and take the stock in ONE transaction.
        #    The conditional UPDATE only succeeds if enough stock is still left, so two
        #    customers can never both buy the last piece. If anything fails, the whole
        #    order is rolled back and no stock is lost.
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
                    amount_paid=total,
                    payment_method=payment_method,
                )

                for item in cart_items:
                    updated = Product.objects.filter(
                        pk=item.product_id, stock__gte=item.quantity
                    ).update(stock=F('stock') - item.quantity)

                    if not updated:
                        raise OutOfStock(item.product.title)

                    OrderItem.objects.create(
                        order=order,
                        product=item.product,
                        price=item.product.price,
                        quantity=item.quantity,
                    )
        except OutOfStock as exc:
            messages.error(request, f"Sorry, {exc} just sold out. Please update your cart.")
            return redirect('store:cart_detail')

        # TODO: for PHONEPE orders, create the payment here and redirect to PhonePe.
        #       Only set order.is_paid = True after PhonePe confirms the payment on your server.

        cart_items.delete()
        cart.delete()
        request.session['last_order_id'] = order.id

        return redirect('store:checkout_success')

    # GET: warn early if something in the cart is no longer available
    for problem in _stock_problems(cart_items):
        messages.warning(request, problem)

    return render(request, 'store/checkout.html', context)


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
# COLLECTIONS
# ---------------------------------------------------------------------------

def collections(request):
    categories = Category.objects.all()
    return render(request, 'store/collections.html', {'categories': categories})

def collection_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    # Filter out hidden products from category pages
    products = Product.objects.filter(category=category, is_active=True)
    return render(request, 'store/collection_detail.html', {
        'category': category,
        'products': products,
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

def all_products(request):
    # 1. Set up the Paginator for your main shop grid
    product_list = Product.objects.all()
    paginator = Paginator(product_list, 12) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # 2. Keep grabbing the 4 newest items for your "Latest Arrivals" strip
    recent_products = Product.objects.order_by('-created')[:4]

    # 3. Pass BOTH variables to your existing index.html template
    return render(request, 'store/index.html', {
        'page_obj': page_obj,
        'recent_products': recent_products,
    })
    
def search_products(request):
    query = request.GET.get('q', '').strip()
    
    if query:
        # Filter for active products matching the query in title or description
        product_list = Product.objects.filter(
            Q(title__icontains=query) | Q(description__icontains=query),
            is_active=True
        )
    else:
        product_list = Product.objects.none()
        
    paginator = Paginator(product_list, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'store/search.html', {'page_obj': page_obj, 'query': query})


def toggle_wishlist(request, product_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'login_required'}, status=401)
        
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        # get_or_create looks for the like. If it doesn't exist, it creates it.
        w_item, created = Wishlist.objects.get_or_create(user=request.user, product=product)
        
        if not created:
            # If it already existed, the user is "un-liking" it
            w_item.delete()
            return JsonResponse({'status': 'removed'})
            
        return JsonResponse({'status': 'added'})