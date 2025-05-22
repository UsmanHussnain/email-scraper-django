import os
import asyncio
import random
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.core.mail import send_mail
from django.contrib import messages
import pandas as pd
from .models import UploadedFile
from .email_scraper import process_excel

# In-memory chat history (temporary, replace with database later)
CHAT_HISTORY = {}

# Dummy email templates for guest posting
DUMMY_EMAIL_TEMPLATES = [
    {
        'subject': 'Guest Post Opportunity for Your Website',
        'body': 'Hello,\n\nI hope this email finds you well! My name is [Your Name], and I’m reaching out to discuss a potential guest post opportunity for your website. We specialize in creating high-quality, engaging content that aligns with your audience’s interests.\n\nI’d love to contribute a well-researched article that provides value to your readers. Please let me know if you’re open to this idea, and I can share some topic suggestions.\n\nLooking forward to hearing from you!\n\n'
    },
    {
        'subject': 'Collaboration Proposal: Guest Blog Post',
        'body': 'Hi there,\n\nI’m [Your Name], a content creator passionate about [your niche]. I’ve been following your website and love the content you share. I’d like to propose a guest blog post that complements your site’s theme and adds value for your readers.\n\nIf you’re interested, I can send over a few topic ideas or work with any guidelines you provide.\n\nLet’s connect and discuss further!\n\n'
    },
    {
        'subject': 'Interested in a Guest Post Partnership?',
        'body': 'Dear [Website Owner],\n\nGreetings! I’m [Your Name], and I specialize in crafting informative and engaging content. I believe a guest post on your website could be a great way to share valuable insights with your audience.\n\nI’m happy to write on a topic that fits your site’s focus. Please let me know your guest posting guidelines or any preferred topics.\n\nExcited to collaborate!\n\n'
    },
    {
        'subject': 'Let’s Boost Your Site with a Guest Post',
        'body': 'Hello,\n\nMy name is [Your Name], and I’m a writer with a passion for creating content that resonates with readers. I’d love to contribute a guest post to your website, offering fresh perspectives and actionable insights.\n\nIf this sounds interesting, I can provide topic ideas or follow your editorial guidelines.\n\nLooking forward to your response!\n\n'
    }
]

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
        uploaded_files = UploadedFile.objects.all().order_by('-uploaded_at')
        latest_file = uploaded_files[0] if uploaded_files.exists() else None
        selected_file = request.GET.get('file')
        if selected_file:
            try:
                selected_file_obj = UploadedFile.objects.get(file=selected_file)
                file_path = os.path.join(settings.MEDIA_ROOT, selected_file_obj.file.name)
            except UploadedFile.DoesNotExist:
                file_path = os.path.join(settings.MEDIA_ROOT, latest_file.file.name) if latest_file else None
        elif latest_file:
            file_path = os.path.join(settings.MEDIA_ROOT, latest_file.file.name)
        else:
            return render(request, 'base/email_display.html', {"error": "No file attached. Please upload a new Excel file."})
        if not file_path or not os.path.exists(file_path):
            return render(request, 'base/email_display.html', {"error": "No file attached. Please upload a new Excel file."})
        df = pd.read_excel(file_path)
        df.columns = [col.strip().lower() for col in df.columns]
        stats = {
            'total': len(df),
            'emails_found': sum(1 for _, row in df.iterrows() if '@' in str(row.get('emails', '')) and row.get('emails') != 'No Email'),
            'no_email': sum(1 for _, row in df.iterrows() if str(row.get('emails', '')).strip() == 'No Email'),
            'contact_pages': sum(1 for _, row in df.iterrows() if 'http' in str(row.get('contact_url', '')).lower() and row.get('contact_url') != 'No Contact'),
            'no_contact': sum(1 for _, row in df.iterrows() if str(row.get('contact_url', '')).strip() == 'No Contact')
        }
        email_list = []
        for _, row in df.iterrows():
            website = row.get('website', '').strip()
            emails = row.get('emails', 'No Email').strip()
            contact_url = row.get('contact_url', 'No Contact').strip()
            domain_age = row.get('domain age', 'N/A').strip()
            if website:
                if not website.startswith(('http://', 'https://')):
                    website = f'http://{website}'
                email_list.append({
                    'website': website,
                    'emails': emails,
                    'contact_url': contact_url,
                    'domain_age': domain_age,
                    'original_website': row['website'],
                    'is_contact_url': 'http' in contact_url.lower() and contact_url != 'No Contact'
                })
        download_url = os.path.join(settings.MEDIA_URL, (selected_file_obj.file.name if selected_file else latest_file.file.name)).replace('\\', '/')
        context = {
            "email_list": email_list,
            "download_url": download_url,
            "total_count": stats['total'],
            "email_found_count": stats['emails_found'],
            "no_email_count": stats['no_email'],
            "contact_page_count": stats['contact_pages'],
            "no_contact_count": stats['no_contact'],
            "filename": (selected_file_obj.file.name if selected_file else latest_file.file.name),
            "uploaded_files": uploaded_files
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
            new_contact_url = request.POST.get('contact_url', '').strip()
            filename = request.POST.get('filename')
            action = request.POST.get('action', 'update')
            if not all([website, filename]):
                return JsonResponse({'status': 'error', 'message': 'Missing parameters'}, status=400)
            file_path = os.path.join(settings.MEDIA_ROOT, filename)
            df = pd.read_excel(file_path)
            df.columns = df.columns.str.strip().str.lower()
            mask = df['website'].astype(str).str.strip() == str(website).strip()
            if not mask.any():
                return JsonResponse({'status': 'error', 'message': 'Website not found'}, status=404)
            current_email = df.loc[mask, 'emails'].iloc[0]
            current_contact = df.loc[mask, 'contact_url'].iloc[0]
            was_email = '@' in str(current_email) and current_email != 'No Email'
            was_contact = 'http' in str(current_contact).lower() and current_contact != 'No Contact'
            if action == 'delete':
                df.loc[mask, 'emails'] = 'No Email'
            else:
                if new_email:
                    df.loc[mask, 'emails'] = new_email
                elif 'email' in request.POST:
                    df.loc[mask, 'emails'] = 'No Email'
                if new_contact_url:
                    df.loc[mask, 'contact_url'] = new_contact_url
                elif 'contact_url' in request.POST:
                    df.loc[mask, 'contact_url'] = 'No Contact'
            df.to_excel(file_path, index=False)
            is_email = '@' in str(df.loc[mask, 'emails'].iloc[0]) and df.loc[mask, 'emails'].iloc[0] != 'No Email'
            is_contact = 'http' in str(df.loc[mask, 'contact_url'].iloc[0]).lower() and df.loc[mask, 'contact_url'].iloc[0] != 'No Contact'
            stats_update = {
                'emails_found': 0,
                'no_email': 0,
                'contact_pages': 0,
                'no_contact': 0
            }
            if was_email and not is_email:
                stats_update['emails_found'] = -1
                stats_update['no_email'] = 1
            elif not was_email and is_email:
                stats_update['emails_found'] = 1
                stats_update['no_email'] = -1
            if was_contact and not is_contact:
                stats_update['contact_pages'] = -1
                stats_update['no_contact'] = 1
            elif not was_contact and is_contact:
                stats_update['contact_pages'] = 1
                stats_update['no_contact'] = -1
            df = pd.read_excel(file_path)
            full_stats = {
                'total': len(df),
                'emails_found': sum(1 for _, row in df.iterrows() if '@' in str(row.get('emails', '')) and row.get('emails') != 'No Email'),
                'no_email': sum(1 for _, row in df.iterrows() if str(row.get('emails', '')).strip() == 'No Email'),
                'contact_pages': sum(1 for _, row in df.iterrows() if 'http' in str(row.get('contact_url', '')).lower() and row.get('contact_url') != 'No Contact'),
                'no_contact': sum(1 for _, row in df.iterrows() if str(row.get('contact_url', '')).strip() == 'No Contact')
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

@login_required
def compose_email(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        body = request.POST.get('body')
        try:
            # Split comma-separated emails and clean them
            email_list = [e.strip() for e in email.split(',') if e.strip()]
            valid_emails = []
            invalid_emails = []

            # Validate emails (basic check for @ and non-empty)
            for e in email_list:
                if '@' in e and '.' in e.split('@')[1]:
                    valid_emails.append(e)
                else:
                    invalid_emails.append(e)

            if not valid_emails:
                messages.error(request, 'No valid email addresses provided.')
                return render(request, 'base/compose_email.html', {
                    'email': email,
                    'subject': subject,
                    'body': body
                })

            # Send email to all valid recipients
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=valid_emails,
                fail_silently=False,
            )

            # Store sent email in chat history
            for recipient in valid_emails:
                if recipient not in CHAT_HISTORY:
                    CHAT_HISTORY[recipient] = []
                CHAT_HISTORY[recipient].append({
                    'sent': True,
                    'message': body,
                    'timestamp': '05:36 PM PKT, May 21, 2025',  # Current time
                    'from': settings.DEFAULT_FROM_EMAIL,
                    'to': recipient
                })

            # Prepare success message
            success_message = f'Email sent successfully to {", ".join(valid_emails)}.'
            if invalid_emails:
                success_message += f' Invalid emails skipped: {", ".join(invalid_emails)}.'
            messages.success(request, success_message)
            # Redirect to chat page with the first valid email
            return redirect('chat', email=valid_emails[0])

        except Exception as e:
            messages.error(request, f'Error sending email: {str(e)}')
            return render(request, 'base/compose_email.html', {
                'email': email,
                'subject': subject,
                'body': body
            })
    else:
        email = request.GET.get('email', '')
        # Select a random dummy template
        selected_template = random.choice(DUMMY_EMAIL_TEMPLATES)
        subject = selected_template['subject']
        # Add user's name to the body
        user_name = f"{request.user.first_name} {request.user.last_name}".strip()
        if not user_name:
            user_name = request.user.username  # Fallback to username if names are empty
        body = f"{selected_template['body']}Regards,\n{user_name}"
        context = {
            'email': email,
            'subject': subject,
            'body': body
        }
        return render(request, 'base/compose_email.html', context)

@login_required
def chat(request, email):
    if email not in CHAT_HISTORY:
        CHAT_HISTORY[email] = []
        # Add a dummy received message for demo
        CHAT_HISTORY[email].append({
            'sent': False,
            'message': f'Thanks for your email! Looking forward to collaborating. - {email}',
            'timestamp': '05:40 PM PKT, May 21, 2025',
            'from': email,
            'to': settings.DEFAULT_FROM_EMAIL
        })

    if request.method == 'POST':
        new_message = request.POST.get('message')
        if new_message:
            CHAT_HISTORY[email].append({
                'sent': True,
                'message': new_message,
                'timestamp': '05:36 PM PKT, May 21, 2025',  # Current time
                'from': settings.DEFAULT_FROM_EMAIL,
                'to': email
            })
            send_mail(
                subject='Follow-up Message',
                message=new_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            messages.success(request, f'Message sent to {email}.')

    # Get all unique emails from chat history for sidebar
    chat_emails = list(CHAT_HISTORY.keys())
    
    context = {
        'selected_email': email,
        'chat_history': CHAT_HISTORY.get(email, []),
        'chat_emails': chat_emails
    }
    return render(request, 'base/chat.html', context)