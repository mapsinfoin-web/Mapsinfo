# store/context_processors.py
from .models import Cart, CartItem, Wishlist
from .views import _cart_id

def cart_item_count(request):
    # Don't run this logic if we are in the Django admin panel
    if 'admin' in request.path:
        return {}

    count = 0
    try:
        cart = Cart.objects.filter(cart_id=_cart_id(request), is_purchased=False).first()
        if not cart and hasattr(request, 'user') and request.user.is_authenticated:
            cart = Cart.objects.filter(user=request.user, is_purchased=False).first()
        if cart:
            cart_items = CartItem.objects.filter(cart=cart, is_active=True)
            for cart_item in cart_items:
                count += cart_item.quantity
    except Exception:
        count = 0

    user_wishlist = []
    if hasattr(request, 'user') and request.user.is_authenticated:
        try:
            user_wishlist = list(Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True))
        except Exception:
            user_wishlist = []

    return {
        'cart_count': count,
        'user_wishlist': user_wishlist,
    }
