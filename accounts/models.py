from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

class CustomUser(AbstractUser):
    email = models.EmailField(_('email address'), unique=True)
    username = models.CharField(_('username'), max_length=150, unique=True)
    first_name = models.CharField(_('first name'), max_length=150)
    last_name = models.CharField(_('last name'), max_length=150)
    
    # Make email required
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']
    
    def __str__(self):
        return self.email
class Bio(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='bios')
    content = models.TextField(max_length=500, help_text="Enter your bio (max 500 characters)")
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Bio for {self.user.username} - {self.created_at.strftime('%Y-%m-%d')}"
    
    class Meta:
        ordering = ['-created_at']