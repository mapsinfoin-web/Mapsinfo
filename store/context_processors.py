# store/context_processors.py
from .models import Cart, CartItem, Wishlist, Notification
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
    try:
        if hasattr(request, 'user') and request.user.is_authenticated:
            user_wishlist = list(Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True))
    except Exception:
        user_wishlist = []

    # Active Store Notifications & Announcements
    notifications = []
    announcements = []
    try:
        notifications = list(Notification.objects.filter(is_active=True).select_related('product', 'category')[:10])
        announcements = [n for n in notifications if n.show_in_announcement_bar]
    except Exception:
        notifications = []
        announcements = []

    return {
        'cart_count': count,
        'user_wishlist': user_wishlist,
        'store_notifications': notifications,
        'store_notifications_count': len(notifications),
        'store_announcements': announcements,
    }
