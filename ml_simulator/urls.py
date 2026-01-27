"""
URL configuration for ml_simulator project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.urls import re_path
from django.contrib.auth import views as auth_views
from django.views.decorators.cache import cache_control


def redirect_to_frontend(request):
    # Ortama göre frontend URL'si
    frontend_url = "https://ml-simulator-fe.vercel.app" if not settings.DEBUG else "http://localhost:3000"
    return redirect(frontend_url)

urlpatterns = [
    path('', redirect_to_frontend),
    path('admin/', admin.site.urls),
    path('api/', include('my_app.urls')),
]

# Static and media files
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', cache_control(max_age=31536000, public=True)(serve), {'document_root': settings.MEDIA_ROOT})]

admin.site.site_header = "Eğitim Yönetim Portalı"

urlpatterns += [
    path('auth/password-reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('auth/password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('auth/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('auth/reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
