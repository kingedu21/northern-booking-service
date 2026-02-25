from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from app.views import CustomPasswordResetView, payment_success
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # Include app URLs
    path('', include('app.urls')),

    # Password reset URLs
    path('forgot-password/', CustomPasswordResetView.as_view(), name='password_reset'),
    path(
        'forgot-password/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='reset_done.html'),
        name='password_reset_done'
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(template_name='reset_confirm.html'),
        name='password_reset_confirm'
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(template_name='reset_complete.html'),
        name='password_reset_complete'
    ),

    path('success/', payment_success, name='payment_success'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)



