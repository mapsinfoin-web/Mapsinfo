from django.shortcuts import render, redirect, get_object_or_404
from .models import Product, Cart, CartItem, Order, OrderItem, Category, ContactInquiry
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from .forms import CustomRegistrationForm
from django.contrib.auth.decorators import login_required    
from .models import Product, Cart, CartItem, Order, OrderItem, Category

def all_products(request):
    # Get all products (in case you need them elsewhere)
    products = Product.objects.all()
    
    # Get just the 4 newest products for the "Latest Arrivals" section
    recent_products = Product.objects.filter(in_stock=True).order_by('-created')[:4]
    
    # Send BOTH variables to the home.html template
    return render(request, 'store/home.html', {
        'products': products,
        'recent_products': recent_products
    })

def product_detail(request, pk):
    # Fetch the product by its Primary Key (pk) / ID
    product = get_object_or_404(Product, pk=pk, in_stock=True)
    return render(request, 'store/product_detail.html', {'product': product})

def _cart_id(request):
    cart = request.session.session_key
    if not cart:
        cart = request.session.create()
    return cart

def add_cart(request, product_id):
    product = Product.objects.get(id=product_id)
    
    # 1. Get or Create the Cart for the current session
    try:
        cart = Cart.objects.get(cart_id=_cart_id(request))
    except Cart.DoesNotExist:
        cart = Cart.objects.create(cart_id=_cart_id(request))
        cart.save()

    # 2. Get or Create the CartItem
    try:
        cart_item = CartItem.objects.get(product=product, cart=cart)
        cart_item.quantity += 1 # If it's already in the cart, just increase the quantity
        cart_item.save()
    except CartItem.DoesNotExist:
        cart_item = CartItem.objects.create(product=product, cart=cart, quantity=1)
        cart_item.save()
        
    return redirect('store:cart_detail')

def cart_detail(request):
    total = 0
    cart_items = None
    try:
        cart = Cart.objects.get(cart_id=_cart_id(request))
        cart_items = CartItem.objects.filter(cart=cart, is_active=True)
        for cart_item in cart_items:
            total += (cart_item.product.price * cart_item.quantity)
    except Cart.DoesNotExist:
        pass # If the cart doesn't exist, total stays 0 and cart_items stays None

    return render(request, 'store/cart.html', {
        'cart_items': cart_items,
        'total': total,
    })

# --- NEW REMOVE FUNCTIONS ---

def remove_cart(request, product_id):
    cart = Cart.objects.get(cart_id=_cart_id(request))
    product = get_object_or_404(Product, id=product_id)
    try:
        cart_item = CartItem.objects.get(product=product, cart=cart)
        if cart_item.quantity > 1:
            cart_item.quantity -= 1
            cart_item.save()
        else:
            cart_item.delete()
    except CartItem.DoesNotExist:
        pass
    return redirect('store:cart_detail')

def remove_cart_item(request, product_id):
    cart = Cart.objects.get(cart_id=_cart_id(request))
    product = get_object_or_404(Product, id=product_id)
    try:
        cart_item = CartItem.objects.get(product=product, cart=cart)
        cart_item.delete()
    except CartItem.DoesNotExist:
        pass
    return redirect('store:cart_detail')

# --- AUTHENTICATION VIEWS ---

def register_user(request):
    if request.method == 'POST':
        form = CustomRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user) # Automatically log the user in after registration
            return redirect('store:all_products')
    else:
        form = CustomRegistrationForm()
    return render(request, 'store/register.html', {'form': form})

def login_user(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('store:all_products')
    else:
        form = AuthenticationForm()
    return render(request, 'store/login.html', {'form': form})

def logout_user(request):
    logout(request)
    return redirect('store:login_user')

# --- CHECKOUT VIEWS ---

def checkout(request):
    try:
        cart = Cart.objects.get(cart_id=_cart_id(request))
        cart_items = CartItem.objects.filter(cart=cart, is_active=True)
    except Cart.DoesNotExist:
        return redirect('store:all_products') # Redirect if cart is empty

    total = sum([item.product.price * item.quantity for item in cart_items])

    if request.method == 'POST':
        # 1. Capture the form data
        full_name = request.POST.get('full_name')
        email = request.POST.get('email')
        shipping_address = request.POST.get('shipping_address')
        city = request.POST.get('city')
        postal_code = request.POST.get('postal_code')

        # 2. Create the permanent Order
        order = Order.objects.create(
            user=request.user if request.user.is_authenticated else None,
            full_name=full_name,
            email=email,
            shipping_address=shipping_address,
            city=city,
            postal_code=postal_code,
            amount_paid=total
        )

        # 3. Snapshot the cart items into permanent OrderItems
        for item in cart_items:
            OrderItem.objects.create(
                order=order,
                product=item.product,
                price=item.product.price,
                quantity=item.quantity
            )

        # 4. Clear the user's cart now that they have purchased
        cart_items.delete()
        cart.delete()

        return redirect('store:checkout_success')

    return render(request, 'store/checkout.html', {
        'cart_items': cart_items,
        'total': total
    })

def checkout_success(request):
    return render(request, 'store/checkout_success.html')

def home(request):
    # Grab the 4 most recently added products that are in stock
    recent_products = Product.objects.filter(in_stock=True).order_by('-created')[:4]
    
    return render(request, 'store/home.html', {
        'recent_products': recent_products
    })
    
# --- CUSTOMER DASHBOARD ---

@login_required(login_url='store:login_user')
def my_orders(request):
    # Fetch only the orders that belong to the logged-in user, newest first
    orders = Order.objects.filter(user=request.user).order_by('-date_ordered')
    
    return render(request, 'store/my_orders.html', {
        'orders': orders
    })
    
# --- COLLECTIONS VIEWS ---

def collections(request):
    # Fetch all categories from the database
    categories = Category.objects.all()
    return render(request, 'store/collections.html', {
        'categories': categories
    })

def collection_detail(request, slug):
    # Fetch the specific category by its slug
    category = get_object_or_404(Category, slug=slug)
    # Fetch only products that belong to this category
    products = Product.objects.filter(category=category, in_stock=True)
    
    return render(request, 'store/collection_detail.html', {
        'category': category,
        'products': products
    })
    
# --- ABOUT PAGE VIEW ---

def about(request):
    return render(request, 'store/about.html')

# --- CONTACT PAGE VIEW ---

def contact(request):
    if request.method == 'POST':
        # 1. Capture the data from the form
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # 2. Save it to the database
        ContactInquiry.objects.create(
            name=name,
            email=email,
            subject=subject,
            message=message
        )
        
        # 3. Create a success message and redirect so the form clears
        messages.success(request, "Thank you. Your inquiry has been forwarded to our atelier.")
        return redirect('store:contact')
        
    return render(request, 'store/contact.html')