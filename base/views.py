import os
import asyncio
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from .models import UploadedFile
import pandas as pd
from .email_scraper import process_excel

@login_required
def upload_excel(request):
    if request.method == 'POST' and 'excel_file' in request.FILES:
        excel_file = request.FILES['excel_file']
        file_path = os.path.join(settings.MEDIA_ROOT, excel_file.name)
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        with open(file_path, 'wb+') as destination:
            for chunk in excel_file.chunks():
                destination.write(chunk)

        uploaded_file = UploadedFile.objects.create(file=excel_file.name)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            processed_file, stats = loop.run_until_complete(process_excel(file_path))
            if processed_file:
                return redirect('display_emails')
            else:
                return render(request, 'base/home.html', {'error': 'Failed to process the Excel file. Please check the file format or try again.'})
        except Exception as e:
            print(f"Processing error: {e}")
            return render(request, 'base/home.html', {'error': f'Error processing file: {str(e)}'})
        finally:
            loop.close()
    return render(request, 'base/home.html')

@login_required
def display_emails(request):
    try:
        latest_file = UploadedFile.objects.latest('uploaded_at')
        file_path = os.path.join(settings.MEDIA_ROOT, latest_file.file.name)
        df = pd.read_excel(file_path)
        df.columns = [col.strip().lower() for col in df.columns]

        # Calculate stats from the DataFrame
        stats = {
            'total': len(df),
            'emails_found': 0,
            'contact_pages': 0,
            'no_contact': 0
        }

        for _, row in df.iterrows():
            emails = str(row.get('emails', 'No Email No Contact')).strip()
            if '@' in emails:
                stats['emails_found'] += 1
            elif 'http' in emails.lower():
                stats['contact_pages'] += 1
            else:
                stats['no_contact'] += 1

        email_list = []
        for _, row in df.iterrows():
            website = row.get('website', '').strip()
            emails = row.get('emails', 'No Email No Contact').strip()
            domain_age = row.get('domain age', 'N/A').strip()
            if website:
                if not website.startswith(('http://', 'https://')):
                    website = f'http://{website}'
                email_list.append({
                    'website': website,
                    'emails': emails,
                    'domain_age': domain_age,
                    'original_website': row['website'],
                    'is_contact_url': 'http' in emails.lower()
                })

        download_url = os.path.join(settings.MEDIA_URL, latest_file.file.name).replace('\\', '/')
        context = {
            "email_list": email_list,
            "download_url": download_url,
            "total_count": stats['total'],
            "email_found_count": stats['emails_found'],
            "contact_page_count": stats['contact_pages'],
            "no_contact_count": stats['no_contact'],
            "filename": latest_file.file.name
        }
        return render(request, 'base/email_display.html', context)
    except Exception as e:
        print(f"Display error: {e}")
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
            
            # Get current values for stats calculation
            current_value = df.loc[mask, 'emails'].iloc[0]
            was_email = '@' in str(current_value)
            was_contact = not was_email and any(
                x in str(current_value).lower() 
                for x in ['http://', 'https://']
            )
            
            if action == 'delete':
                new_value = 'No Email No Contact'
                df.loc[mask, 'emails'] = new_value
            else:
                new_value = new_email
                df.loc[mask, 'emails'] = new_value
            
            # Save the updated file
            df.to_excel(file_path, index=False)
            
            # Calculate stats changes
            is_email = '@' in new_value
            is_contact = not is_email and any(
                x in new_value.lower() 
                for x in ['http://', 'https://']
            )
            
            stats_update = {
                'emails_found': 0,
                'contact_pages': 0,
                'no_contact': 0
            }
            
            if was_email and not is_email:
                stats_update['emails_found'] = -1
            elif not was_email and is_email:
                stats_update['emails_found'] = 1
            
            if was_contact and not is_contact:
                stats_update['contact_pages'] = -1
            elif not was_contact and is_contact:
                stats_update['contact_pages'] = 1
            
            if (not was_email and not was_contact) and (is_email or is_contact):
                stats_update['no_contact'] = -1
            elif (not is_email and not is_contact) and (was_email or was_contact):
                stats_update['no_contact'] = 1
            
            # Recalculate full stats from the updated file
            df = pd.read_excel(file_path)
            full_stats = {
                'total': len(df),
                'emails_found': sum(1 for _, row in df.iterrows() if '@' in str(row.get('emails', ''))),
                'contact_pages': sum(1 for _, row in df.iterrows() if 'http' in str(row.get('emails', '')).lower() and '@' not in str(row.get('emails', ''))),
                'no_contact': sum(1 for _, row in df.iterrows() if str(row.get('emails', '')).strip() == 'No Email No Contact')
            }

            return JsonResponse({
                'status': 'success',
                'stats_update': stats_update,
                'full_stats': full_stats
            })
            
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