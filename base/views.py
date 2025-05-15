import os
import asyncio
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from .models import UploadedFile
import pandas as pd # type: ignore
from .email_scraper import process_excel

@login_required
def upload_excel(request):
    if request.method == 'POST' and 'excel_file' in request.FILES:
        excel_file = request.FILES['excel_file']
        
        # Create media directory if it doesn't exist
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        
        # Save the file
        file_path = os.path.join(settings.MEDIA_ROOT, excel_file.name)
        with open(file_path, 'wb+') as destination:
            for chunk in excel_file.chunks():
                destination.write(chunk)

        # Save to database
        uploaded_file = UploadedFile.objects.create(file=excel_file.name)
        
        # Process the file
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(process_excel(file_path))
        finally:
            loop.close()
        
        return redirect('display_emails')
    
    return render(request, 'base/home.html')

@login_required
def display_emails(request):
    try:
        # Get the most recent file
        latest_file = UploadedFile.objects.latest('uploaded_at')
        file_path = os.path.join(settings.MEDIA_ROOT, latest_file.file.name)
        
        # Read the Excel file
        df = pd.read_excel(file_path)

        # Standardize column names
        df.columns = df.columns.str.strip().str.lower()
        if 'website' not in df.columns:
            df.rename(columns={df.columns[0]: 'website'}, inplace=True)
        if 'emails' not in df.columns:
            df['emails'] = 'No Email Found'

        # Prepare data for template
        email_list = []
        total_count = 0
        email_found_count = 0
        no_email_count = 0
        
        for _, row in df.iterrows():
            website = row['website']
            emails = row['emails']
            
            # Skip empty website entries
            if pd.isna(website) or str(website).strip() == '':
                continue
            
            # Ensure proper URL formatting
            if not str(website).startswith(('http://', 'https://')):
                website = f'http://{str(website).strip()}'
                
            total_count += 1
            
            # Process emails
            if pd.isna(emails) or str(emails).strip() == '' or str(emails).strip().lower() == 'no email found':
                no_email_count += 1
                emails = 'No Email Found'
            else:
                email_found_count += 1
            
            email_list.append({
                'website': website,
                'emails': str(emails).strip(),
                'original_website': row['website']
            })

        # Generate download URL
        download_url = os.path.join(settings.MEDIA_URL, latest_file.file.name).replace('\\', '/')
        
        context = {
            "email_list": email_list,
            "download_url": download_url,
            "total_count": total_count,
            "email_found_count": email_found_count,
            "no_email_count": no_email_count,
            "filename": latest_file.file.name
        }
        return render(request, 'base/email_display.html', context)

    except Exception as e:
        print(f"Error displaying emails: {e}")
        return render(request, 'base/email_display.html', {"error": str(e)})

@login_required
def update_email(request):
    if request.method == 'POST':
        try:
            website = request.POST.get('website')
            new_email = request.POST.get('email', '').strip()
            filename = request.POST.get('filename')
            action = request.POST.get('action', 'update')
            
            if not all([website, filename]):
                return JsonResponse({'status': 'error', 'message': 'Missing parameters'}, status=400)
            
            file_path = os.path.join(settings.MEDIA_ROOT, filename)
            df = pd.read_excel(file_path)
            
            # Standardize column names
            df.columns = df.columns.str.strip().str.lower()
            
            # Find the row
            mask = df['website'].astype(str).str.strip() == str(website).strip()
            if not mask.any():
                return JsonResponse({'status': 'error', 'message': 'Website not found'}, status=404)
            
            if action == 'delete':
                df.loc[mask, 'emails'] = 'No Email Found'
            else:
                df.loc[mask, 'emails'] = new_email
            
            # Save the updated file
            df.to_excel(file_path, index=False)
            
            return JsonResponse({'status': 'success'})
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@login_required
def download_file(request):
    try:
        latest_file = UploadedFile.objects.latest('uploaded_at')
        file_path = os.path.join(settings.MEDIA_ROOT, latest_file.file.name)
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                response['Content-Disposition'] = f'attachment; filename="{latest_file.file.name}"'
                return response
        return HttpResponse("File not found", status=404)
    except Exception as e:
        return HttpResponse(f"Error: {str(e)}", status=500)