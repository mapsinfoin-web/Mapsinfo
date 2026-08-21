# store/context_processors.py
from .models import Cart, CartItem
from .views import _cart_id

def cart_item_count(request):
    count = 0
    # Don't run this logic if we are in the Django admin panel
    if 'admin' in request.path:
        return {}
    else:
        try:
            cart = Cart.objects.filter(cart_id=_cart_id(request))
            if cart.exists():
                cart_items = CartItem.objects.filter(cart=cart.first())
                for cart_item in cart_items:
                    count += cart_item.quantity
        except Cart.DoesNotExist:
            count = 0
            
    return {'cart_count': count}