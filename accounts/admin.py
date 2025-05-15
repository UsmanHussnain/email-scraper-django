from django.contrib import admin
from  .models import *
from base.models import *

# Register your models here.
admin.site.register(UploadedFile)
admin.site.register(CustomUser)