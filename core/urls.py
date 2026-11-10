from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView
from django.templatetags.static import static as static_url
from django.http import HttpResponse


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Allow: /llms.txt",
        "Disallow: /admin/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        "Disallow: /order/",
        "Disallow: /accounts/",
        "Sitemap: " + request.build_absolute_uri('/sitemap.xml'),
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def llms_txt(request):
    """Serves llms.txt standard file for LLMs, crawlers, and AI agents."""
    llms_path = settings.BASE_DIR / 'llms.txt'
    if llms_path.exists():
        content = llms_path.read_text(encoding='utf-8')
    else:
        content = "# MAPSKART\n\n> Luxury Handcrafted Fashion Jewellery\n"
    return HttpResponse(content, content_type="text/markdown; charset=utf-8")


def sitemap_xml(request):
    base_url = request.build_absolute_uri('/').rstrip('/')
    try:
        from store.models import Product, Category
        urls = [
            f"<url><loc>{base_url}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
            f"<url><loc>{base_url}/sale/</loc><changefreq>daily</changefreq><priority>0.9</priority></url>",
            f"<url><loc>{base_url}/collections/</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>",
            f"<url><loc>{base_url}/about/</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>",
            f"<url><loc>{base_url}/contact/</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>",
        ]
        for c in Category.objects.all():
            urls.append(f"<url><loc>{base_url}/collections/{c.slug}/</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>")
        for p in Product.objects.filter(is_active=True):
            urls.append(f"<url><loc>{base_url}/item/{p.pk}/</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>")
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + '\n'.join(urls) + '\n</urlset>'
    except Exception:
        # Fallback to static sitemap file
        sitemap_path = settings.BASE_DIR / 'sitemap.xml'
        if sitemap_path.exists():
            xml = sitemap_path.read_text(encoding='utf-8').replace('https://mapskart.info.in', base_url)
        else:
            xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n<url><loc>{base_url}/</loc></url>\n</urlset>'
    return HttpResponse(xml, content_type="application/xml")


def bing_site_auth(request):
    """Serves BingSiteAuth.xml for Bing Webmaster Tools verification."""
    auth_path = settings.BASE_DIR / 'BingSiteAuth.xml'
    if auth_path.exists():
        content = auth_path.read_text(encoding='utf-8')
    else:
        content = '<?xml version="1.0"?>\n<users>\n  <user>BING_WEBMASTER_VERIFICATION_CODE</user>\n</users>'
    return HttpResponse(content, content_type="application/xml")


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('store.urls')),
    path('accounts/', include('allauth.urls')),
    path('favicon.ico', RedirectView.as_view(url=static_url('1.png'), permanent=True)),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap_xml, name='sitemap_xml'),
    path('llms.txt', llms_txt, name='llms_txt'),
    path('BingSiteAuth.xml', bing_site_auth, name='bing_site_auth'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Custom error pages (these only take effect when DEBUG = False)
handler400 = 'store.views.bad_request'
handler403 = 'store.views.permission_denied'
handler404 = 'store.views.page_not_found'
handler500 = 'store.views.server_error'
