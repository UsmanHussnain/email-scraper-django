from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from .views import *

urlpatterns = [
    path('', upload_excel, name='upload_excel'),
    path('emails/', display_emails, name='display_emails'),
    path('download/', download_file, name='download_file'),
    path('update-email/', update_email, name='update_email'),
    path('compose-email/', compose_email, name='compose_email'),
    path('chat/', chat, name='chat_list'),
    path('chat/<str:contact_email>/', chat, name='chat'),
    path('delete-chat/<str:contact_email>/', delete_chat, name='delete_chat'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])