from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from .views import *

urlpatterns = [
    path('', upload_excel, name='upload_excel'),
    path('emails/', display_emails, name='display_emails'),
    path('download/', download_file, name='download_file'),
    path('update-email/', update_email, name='update_email'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])