import os
import asyncio
import random
import imaplib
import email as email_module
import base64
import re
from email.header import decode_header
from email.mime.image import MIMEImage
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.core.mail import send_mail, EmailMessage as DjangoEmailMessage
from django.contrib import messages
import pandas as pd
from .models import UploadedFile, EmailMessage
from .email_scraper import process_excel
from datetime import datetime
import pytz
from django.contrib.auth import get_user_model

# Dummy email templates for guest posting
DUMMY_EMAIL_TEMPLATES = [
    {
        'subject': 'Guest Post Opportunity for Your Website',
        'body': 'Hello,\n\nI hope this email finds you well! My name is [Your Name], and I\'m reaching out to discuss a potential guest post opportunity for your website. We specialize in creating high-quality, engaging content that aligns with your audience\'s interests.\n\nI\'d love to contribute a well-researched article that provides value to your readers. Please let me know if you\'re open to this idea, and I can share some topic suggestions.\n\nLooking forward to hearing from you!\n\n'
    },
    {
        'subject': 'Collaboration Proposal: Guest Blog Post',
        'body': 'Hi there,\n\nI\'m [Your Name], a content creator passionate about [your niche]. I\'ve been following your website and love the content you share. I\'d like to propose a guest blog post that complements your site\'s theme and adds value for your readers.\n\nIf you\'re interested, I can send over a few topic ideas or work with any guidelines you provide.\n\nLet\'s connect and discuss further!\n\n'
    },
    {
        'subject': 'Interested in a Guest Post Partnership?',
        'body': 'Dear [Website Owner],\n\nGreetings! I\'m [Your Name], and I specialize in crafting informative and engaging content. I believe a guest post on your website could be a great way to share valuable insights with your audience.\n\nI\'m happy to write on a topic that fits your site\'s focus. Please let me know your guest posting guidelines or any preferred topics.\n\nExcited to collaborate!\n\n'
    },
    {
        'subject': 'Let\'s Boost Your Site with a Guest Post',
        'body': 'Hello,\n\nMy name is [Your Name], and I\'m a writer with a passion for creating content that resonates with readers. I\'d love to contribute a guest post to your website, offering fresh perspectives and actionable insights.\n\nIf this sounds interesting, I can provide topic ideas or follow your editorial guidelines.\n\nLooking forward to your response!\n\n'
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
            'email_found_count': stats['emails_found'],
            'no_email_count': stats['no_email'],
            'contact_page_count': stats['contact_pages'],
            'no_contact_count': stats['no_contact'],
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
        user_email = request.POST.get('email')
        subject = request.POST.get('subject')
        body = request.POST.get('body')
        try:
            # Split comma-separated emails and clean them
            email_list = [e.strip() for e in user_email.split(',') if e.strip()]
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
                    'email': user_email,
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

            # Store sent emails in database
            for recipient in valid_emails:
                EmailMessage.objects.create(
                    user=request.user,
                    sender=settings.DEFAULT_FROM_EMAIL,
                    receiver=recipient,
                    message=body,
                    is_sent=True
                )

            # Prepare success message
            success_message = f'Email sent successfully to {", ".join(valid_emails)}.'
            if invalid_emails:
                success_message += f' Invalid emails skipped: {", ".join(invalid_emails)}.'
            messages.success(request, success_message)
            # Redirect to chat page with the first valid email
            return redirect('chat', contact_email=valid_emails[0])

        except Exception as e:
            messages.error(request, f'Error sending email: {str(e)}')
            return render(request, 'base/compose_email.html', {
                'email': user_email,
                'subject': subject,
                'body': body
            })
    else:
        user_email = request.GET.get('email', '')
        # Select a random dummy template
        selected_template = random.choice(DUMMY_EMAIL_TEMPLATES)
        subject = selected_template['subject']
        # Add user's name to the body
        user_name = f"{request.user.first_name} {request.user.last_name}".strip()
        if not user_name:
            user_name = request.user.username  # Fallback to username if names are empty
        body = f"{selected_template['body']}Regards,\n{user_name}"
        context = {
            'email': user_email,
            'subject': subject,
            'body': body
        }
        return render(request, 'base/compose_email.html', context)

def extract_latest_reply(email_body):
    """Extract only the latest reply from email thread"""
    # Common email thread separators
    separators = [
        '-----Original Message-----',
        '--- On ',
        'On ',
        'From:',
        '________________________________',
        '> On',
        '>>',
        'wrote:',
        '\n>',
        'Sent from',
        'Get Outlook for',
        '-----Forwarded Message-----'
    ]
    
    lines = email_body.split('\n')
    clean_lines = []
    
    for line in lines:
        line = line.strip()
        
        # Check if this line starts a thread/quote
        is_thread_start = False
        for separator in separators:
            if separator.lower() in line.lower():
                is_thread_start = True
                break
        
        # If we hit a thread separator, stop processing
        if is_thread_start:
            break
            
        # Skip lines that look like quoted text
        if line.startswith('>') or line.startswith('>>'):
            continue
            
        # Skip empty lines at the start but keep them in the middle
        if line or clean_lines:
            clean_lines.append(line)
    
    # Join and clean up
    result = '\n'.join(clean_lines).strip()
    
    # Remove excessive whitespace
    result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)
    
    return result

def markdown_to_html(text):
    """Convert basic Markdown to HTML for plain text emails"""
    # Convert **bold** or *bold* to <strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<strong>\1</strong>', text)
    # Convert _italic_ to <em>
    text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)
    # Convert newlines to <br> for HTML rendering
    text = text.replace('\n', '<br>')
    return text

def clean_email_body(msg):
    """Extract clean text from email message, preserving HTML styling for text/html"""
    body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='ignore')
                        # Convert basic Markdown to HTML for plain text
                        body = markdown_to_html(body)
                        break
                except Exception:
                    continue
            elif content_type == 'text/html' and not body:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='ignore')
                        # Don't strip HTML tags; keep the styling
                        break
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='ignore')
                if msg.get_content_type() == 'text/html':
                    # Keep HTML as-is
                    pass
                else:
                    # Convert Markdown for plain text
                    body = markdown_to_html(body)
        except Exception:
            body = str(msg.get_payload())
    
    # Extract only the latest reply
    body = extract_latest_reply(body)
    
    return body.strip()

def extract_attachments(msg, message_obj):
    """Extract attachments and save them to the EmailMessage object"""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if part.get('Content-Disposition') is None:
                continue
            filename = part.get_filename()
            if filename:
                decoded_filename = decode_header(filename)[0][0]
                if isinstance(decoded_filename, bytes):
                    decoded_filename = decoded_filename.decode()
                file_path = os.path.join(settings.MEDIA_ROOT, 'email_attachments', decoded_filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'wb') as f:
                    f.write(part.get_payload(decode=True))
                message_obj.attachment = os.path.join('email_attachments', decoded_filename)
                message_obj.has_attachment = True
                message_obj.save()
                attachments.append(decoded_filename)
    return attachments

def get_email_date(msg):
    """Extract and parse email date with Pakistan timezone"""
    try:
        date_str = msg.get('Date')
        if date_str:
            from email.utils import parsedate_to_datetime
            email_date = parsedate_to_datetime(date_str)
            
            # Convert to Pakistan timezone
            pakistan_tz = pytz.timezone('Asia/Karachi')
            if email_date.tzinfo is None:
                email_date = pytz.utc.localize(email_date)
            
            return email_date.astimezone(pakistan_tz)
    except Exception:
        pass
    
    # Return current time in Pakistan timezone as fallback
    pakistan_tz = pytz.timezone('Asia/Karachi')
    return datetime.now(pakistan_tz)

def delete_emails_from_gmail(email_address, gmail_user, gmail_password):
    """Delete emails from Gmail inbox using IMAP"""
    try:
        # Connect to Gmail
        imap_server = imaplib.IMAP4_SSL('imap.gmail.com')
        imap_server.login(gmail_user, gmail_password)
        
        # Select inbox
        imap_server.select('INBOX')
        
        # Search for emails from the specific contact
        search_criteria = f'(FROM "{email_address}")'
        _, message_numbers = imap_server.search(None, search_criteria)
        
        deleted_count = 0
        if message_numbers[0]:
            for num in message_numbers[0].split():
                try:
                    # Mark email as deleted
                    imap_server.store(num, '+FLAGS', '\\Deleted')
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting email {num}: {e}")
                    continue
        
        # Expunge to permanently delete
        imap_server.expunge()
        
        # Also check sent folder
        imap_server.select('"[Gmail]/Sent Mail"')
        search_criteria = f'(TO "{email_address}")'
        _, message_numbers = imap_server.search(None, search_criteria)
        
        if message_numbers[0]:
            for num in message_numbers[0].split():
                try:
                    # Mark email as deleted
                    imap_server.store(num, '+FLAGS', '\\Deleted')
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting sent email {num}: {e}")
                    continue
        
        # Expunge sent folder
        imap_server.expunge()
        imap_server.logout()
        
        return True, deleted_count
        
    except Exception as e:
        print(f"Gmail deletion error: {e}")
        return False, 0

@login_required
def delete_chat(request, contact_email):
    """Delete entire chat conversation with a contact"""
    if request.method == 'POST':
        try:
            # Delete all messages from database for this conversation
            deleted_messages = EmailMessage.objects.filter(
                user=request.user,
                receiver=contact_email
            ) | EmailMessage.objects.filter(
                user=request.user,
                sender=contact_email
            )
            
            message_count = deleted_messages.count()
            deleted_messages.delete()
            
            # Try to delete emails from Gmail as well
            gmail_deleted = False
            gmail_count = 0
            try:
                gmail_deleted, gmail_count = delete_emails_from_gmail(
                    contact_email, 
                    settings.EMAIL_HOST_USER, 
                    settings.EMAIL_HOST_PASSWORD
                )
            except Exception as e:
                print(f"Gmail deletion failed: {e}")
            
            # Prepare success message
            success_msg = f"Chat with {contact_email} deleted successfully. "
            success_msg += f"Deleted {message_count} messages from database."
            
            if gmail_deleted and gmail_count > 0:
                success_msg += f" Also deleted {gmail_count} emails from Gmail."
            elif not gmail_deleted:
                success_msg += " Note: Could not delete emails from Gmail automatically."
            
            messages.success(request, success_msg)
            
            # Return JSON response for AJAX
            return JsonResponse({
                'status': 'success',
                'message': success_msg,
                'redirect_url': '/emails/'  # Redirect to emails list
            })
            
        except Exception as e:
            error_msg = f"Error deleting chat: {str(e)}"
            messages.error(request, error_msg)
            return JsonResponse({
                'status': 'error',
                'message': error_msg
            }, status=500)
    
    return JsonResponse({
        'status': 'error',
        'message': 'Invalid request method'
    }, status=405)

def extract_base64_images(html_content):
    """Extract base64 images from HTML content and save them to files"""
    images = []
    pattern = r'<img[^>]+src="data:image/[^;]+;base64,([^"]+)"'
    matches = re.findall(pattern, html_content)
    
    for idx, base64_str in enumerate(matches):
        try:
            image_data = base64.b64decode(base64_str)
            img_format_match = re.search(r'data:image/(\w+);base64', html_content)
            img_format = img_format_match.group(1) if img_format_match else 'png'
            filename = f"inline_image_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{idx}.{img_format}"
            file_path = os.path.join(settings.MEDIA_ROOT, 'email_attachments', filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'wb') as f:
                f.write(image_data)
            file_url = os.path.join(settings.MEDIA_URL, 'email_attachments', filename)
            html_content = html_content.replace(
                f'data:image/{img_format};base64,{base64_str}',
                f'cid:image_{idx}'
            )
            images.append({
                'path': file_path,
                'cid': f'image_{idx}',
                'url': file_url
            })
        except Exception as e:
            print(f"Error processing base64 image: {e}")
            continue
    
    return html_content, images

@login_required
def chat(request, contact_email=None):
    if contact_email == 'new':
        new_email = request.GET.get('email', '').strip()
        if not new_email or '@' not in new_email:
            messages.error(request, 'Please provide a valid email address to start a new chat.')
            return redirect('display_emails')
        return redirect('chat', contact_email=new_email)

    chat_history = EmailMessage.objects.filter(
        user=request.user,
        receiver=contact_email
    ) | EmailMessage.objects.filter(
        user=request.user,
        sender=contact_email
    ) if contact_email else EmailMessage.objects.none()
    chat_history = chat_history.order_by('timestamp').distinct()

    if request.GET.get('ajax') == 'true':
        last_message_id = int(request.GET.get('last_message_id', 0))
        new_messages = chat_history.filter(id__gt=last_message_id)
        messages_data = []
        for msg in new_messages:
            messages_data.append({
                'id': msg.id,
                'sender': msg.sender,
                'message': msg.message,
                'timestamp': msg.timestamp.strftime('%b %d, %H:%M'),
                'is_sent': msg.is_sent,
                'has_attachment': msg.has_attachment,
                'attachment_url': msg.attachment.url if msg.has_attachment else None,
                'attachment_name': msg.attachment.name.split('/')[-1] if msg.has_attachment else None,
                'inline_images': msg.inline_images if hasattr(msg, 'inline_images') else []
            })
        return JsonResponse({'messages': messages_data})

    if contact_email:
        try:
            imap_server = imaplib.IMAP4_SSL('imap.gmail.com')
            imap_server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            imap_server.select('INBOX')
            search_criteria = f'(FROM "{contact_email}")'
            _, message_numbers = imap_server.search(None, search_criteria)
            
            if message_numbers[0]:
                for num in message_numbers[0].split():
                    try:
                        _, msg_data = imap_server.fetch(num, '(RFC822)')
                        if not msg_data or len(msg_data) < 2:
                            continue
                        raw_email = msg_data[0][1]
                        if not isinstance(raw_email, bytes):
                            continue
                        msg = email_module.message_from_bytes(raw_email)
                        body = clean_email_body(msg)
                        if not body or len(body.strip()) < 3:
                            continue
                        sender = msg.get('From', contact_email)
                        if '<' in sender and '>' in sender:
                            sender = sender.split('<')[1].split('>')[0].strip()
                        message_id = msg.get('Message-ID', None)
                        if not message_id:
                            message_id = f"{sender}_{hash(body)}"
                        if not EmailMessage.objects.filter(user=request.user, message=body, sender=sender).exists():
                            new_message = EmailMessage.objects.create(
                                user=request.user,
                                sender=sender,
                                receiver=settings.DEFAULT_FROM_EMAIL,
                                message=body,
                                is_sent=False,
                                timestamp=get_email_date(msg)
                            )
                            extract_attachments(msg, new_message)
                    except Exception as e:
                        print(f"Error processing individual email: {e}")
                        continue
            imap_server.logout()
        except Exception as e:
            print(f"IMAP Error: {e}")
            pass

    if request.method == 'POST' and contact_email:
        new_message = request.POST.get('message', '').strip()
        attachment = request.FILES.get('attachment') if 'attachment' in request.FILES else None
        
        try:
            pakistan_tz = pytz.timezone('Asia/Karachi')
            current_time = datetime.now(pakistan_tz)
            
            new_message, inline_images = extract_base64_images(new_message)
            
            # Replace cid: references with URLs before sending
            if inline_images:
                for img in inline_images:
                    new_message = new_message.replace(f'cid:{img["cid"]}', img["url"])
            
            email = DjangoEmailMessage(
                subject='Follow-up Message',
                body=new_message if new_message else "Please find the attached file.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[contact_email],
            )
            
            email.content_subtype = 'html'
            
            for img in inline_images:
                with open(img['path'], 'rb') as f:
                    mime_image = MIMEImage(f.read())
                    mime_image.add_header('Content-ID', f"<{img['cid']}>")
                    mime_image.add_header('Content-Disposition', 'inline', filename=os.path.basename(img['path']))
                    email.attach(mime_image)
            
            if attachment:
                email.attach(attachment.name, attachment.read(), attachment.content_type)
            
            email.send(fail_silently=False)
            
            email_message = EmailMessage.objects.create(
                user=request.user,
                sender=settings.DEFAULT_FROM_EMAIL,
                receiver=contact_email,
                message=new_message if new_message else "Sent an attachment.",
                is_sent=True,
                timestamp=current_time,
                has_attachment=bool(attachment),
                inline_images=[img['url'] for img in inline_images]
            )
            
            if attachment:
                email_message.attachment = attachment
                email_message.has_attachment = True
                email_message.save()
            
            return JsonResponse({
                'status': 'success',
                'message': f'Message sent to {contact_email}.',
                'new_message': {
                    'id': email_message.id,
                    'sender': email_message.sender,
                    'message': email_message.message,
                    'timestamp': email_message.timestamp.strftime('%b %d, %H:%M'),
                    'is_sent': email_message.is_sent,
                    'has_attachment': email_message.has_attachment,
                    'attachment_url': email_message.attachment.url if email_message.has_attachment else None,
                    'attachment_name': email_message.attachment.name.split('/')[-1] if email_message.has_attachment else None,
                    'inline_images': email_message.inline_images
                },
                'redirect_url': f'/chat/{contact_email}/'  # Added redirect URL for client-side
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Error sending message: {str(e)}'
            }, status=500)

    sent_emails = EmailMessage.objects.filter(user=request.user, is_sent=True).values_list('receiver', flat=True).distinct()
    received_emails = EmailMessage.objects.filter(user=request.user, is_sent=False).values_list('sender', flat=True).distinct()
    chat_emails = set(list(sent_emails) + list(received_emails))
    
    # Preprocess chat history to replace cid: references with URLs
    processed_chat_history = []
    for message in chat_history:
        processed_message = message.message
        if message.inline_images:
            for img_url in message.inline_images:
                processed_message = processed_message.replace(f'cid:image_', img_url)
        processed_chat_history.append(
            EmailMessage(
                id=message.id,
                user=message.user,
                sender=message.sender,
                receiver=message.receiver,
                message=processed_message,
                is_sent=message.is_sent,
                timestamp=message.timestamp,
                has_attachment=message.has_attachment,
                attachment=message.attachment,
                inline_images=message.inline_images
            )
        )
    
    context = {
        'selected_email': contact_email,
        'chat_history': processed_chat_history,
        'chat_emails': chat_emails
    }
    return render(request, 'base/chat.html', context)