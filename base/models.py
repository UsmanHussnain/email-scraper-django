from django.db import models

class UploadedFile(models.Model):
    file = models.FileField(upload_to='')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
    def __str__(self):
        return self.file.name

    