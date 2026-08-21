from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    path('', views.all_products, name='all_products'),
    path('item/<int:pk>/', views.product_detail, name='product_detail'),
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:product_id>/', views.add_cart, name='add_cart'),
    path('cart/remove/<int:product_id>/', views.remove_cart, name='remove_cart'),
    path('cart/remove_item/<int:product_id>/', views.remove_cart_item, name='remove_cart_item'),
    path('register/', views.register_user, name='register_user'),
    path('login/', views.login_user, name='login_user'),
    path('logout/', views.logout_user, name='logout_user'),
    path('checkout/', views.checkout, name='checkout'),
    path('checkout/success/', views.checkout_success, name='checkout_success'),
    # Customer Dashboard
    path('my-orders/', views.my_orders, name='my_orders'),
    # Collections paths
    path('collections/', views.collections, name='collections'),
    path('collections/<slug:slug>/', views.collection_detail, name='collection_detail'),
    # Pages
    path('about/', views.about, name='about'),
    # Pages
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'), # <-- Add this line
]