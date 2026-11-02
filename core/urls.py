from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('store.urls')),
    path('accounts/', include('allauth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Custom error pages (these only take effect when DEBUG = False)
handler400 = 'store.views.bad_request'
handler403 = 'store.views.permission_denied'
handler404 = 'store.views.page_not_found'
handler500 = 'store.views.server_error'
