# store/context_processors.py
from .models import Cart, CartItem, Wishlist
from .views import _cart_id

def cart_item_count(request):
    # Don't run this logic if we are in the Django admin panel
    if 'admin' in request.path:
        return {}

    count = 0
    try:
        cart = Cart.objects.filter(cart_id=_cart_id(request))
        if cart.exists():
            cart_items = CartItem.objects.filter(cart=cart.first())
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
