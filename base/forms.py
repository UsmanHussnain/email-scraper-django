# forms.py
from django import forms

class ExcelUploadForm(forms.Form):
    excel_file = forms.FileField()

# class EmailUpdateForm(forms.Form):
#     email = forms.EmailField(required=False)  
#     website = forms.CharField(widget=forms.HiddenInput(), required=True)
