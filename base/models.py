from django.db import models
from django.conf import settings

class UploadedFile(models.Model):
    file = models.FileField(upload_to='')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
    def __str__(self):
        return self.file.name

class EmailMessage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    sender = models.EmailField()
    receiver = models.EmailField()
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_sent = models.BooleanField(default=True)
    has_attachment = models.BooleanField(default=False)
    attachment = models.FileField(upload_to='email_attachments/', null=True, blank=True)
    inline_images = models.JSONField(default=list, blank=True)
    message_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    def __str__(self):
        return f"{'Sent' if self.is_sent else 'Received'} message from {self.sender} to {self.receiver}"