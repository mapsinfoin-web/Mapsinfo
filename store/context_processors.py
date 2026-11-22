# store/context_processors.py
from .models import Cart, CartItem, Wishlist, Notification, Category
from .views import _cart_id

WEDDING_OCCASIONS = [
    {
        'key': 'haldi',
        'name': 'Haldi Ceremony',
        'subtitle': 'Radiant Gold, Yellow & Kundan',
        'icon': 'fa-sun',
        'color': '#D97706',
        'bg': '#FEF3C7',
    },
    {
        'key': 'mehendi',
        'name': 'Mehendi Ceremony',
        'subtitle': 'Emerald Greens & Statement Cuffs',
        'icon': 'fa-leaf',
        'color': '#059669',
        'bg': '#D1FAE5',
    },
    {
        'key': 'sangeet',
        'name': 'Sangeet & Cocktail',
        'subtitle': 'Baguettes, Zircon & Royal Sapphire',
        'icon': 'fa-glass-cheers',
        'color': '#2563EB',
        'bg': '#DBEAFE',
    },
    {
        'key': 'bridal',
        'name': 'Grand Wedding & Bridal',
        'subtitle': 'Heritage Chokers with Maang Tikka',
        'icon': 'fa-crown',
        'color': '#DC2626',
        'bg': '#FEE2E2',
    },
    {
        'key': 'reception',
        'name': 'Reception Elegance',
        'subtitle': 'Tiara Sets & Solitaire Drops',
        'icon': 'fa-gem',
        'color': '#7C3AED',
        'bg': '#EDE9FE',
    },
]

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

    nav_categories = []
    try:
        nav_categories = list(Category.objects.filter(parent__isnull=True).exclude(name__icontains='test').exclude(slug__icontains='test').prefetch_related('subcategories').order_by('order', 'id'))
    except Exception:
        nav_categories = []

    return {
        'cart_count': count,
        'user_wishlist': user_wishlist,
        'store_notifications': notifications,
        'store_notifications_count': len(notifications),
        'store_announcements': announcements,
        'nav_categories': nav_categories,
        'wedding_occasions': WEDDING_OCCASIONS,
    }
