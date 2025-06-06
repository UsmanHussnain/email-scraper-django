import re
import os
import asyncio
import requests
import whois
from playwright.async_api import async_playwright
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from urllib.parse import urljoin

# Constants
EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
TIMEOUT = 100000  # 100 seconds
MAX_WORKERS = multiprocessing.cpu_count() * 2
CONTACT_KEYWORDS = ['contact', 'about', 'support', 'help', 'mailto', 'reach', 'connect']
CONTACT_PAGE = ['contact', 'contact-us', 'contactus']
EXCLUDED_EMAIL_PATTERNS = [
    r'^demo@', r'^test@', r'^example@', r'^sample@',
    r'@example\.com$', r'@test\.com$', r'@demo\.com$',
    r'name@yourcompany\.', r'yourname@yourcompany\.', 
    r'company@gmail\.com$', r'your@email\.com$',
    r'info@example\.com$', r'contact@example\.com$',
    r'@yourdomain\.com$', r'^@yourcompany\.com$',
    r'user@example\.com$', r'email@example\.com$',
    r'support@example\.com$', r'sales@example\.com$',
    r'\.js$', r'\.png$', r'\.jpg$', r'\.jpeg$', r'\.gif$', r'\.css$',
    r'react-jsx-runtime@', r'react-dom@', r'react@', r'react-dom-client@',
    r'react-jsx-dev-runtime@'
]

def is_valid_email(email):
    """Validate email to exclude dummy, test, or file-like patterns."""
    for pattern in EXCLUDED_EMAIL_PATTERNS:
        if re.search(pattern, email, re.IGNORECASE):
            return False
    try:
        local, domain = email.split('@')
        if not local or not domain:
            return False
        if not re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', domain):
            return False
        return True
    except:
        return False

def extract_emails_from_text(text):
    """Extract and validate emails using regex."""
    emails = set(re.findall(EMAIL_PATTERN, text, re.IGNORECASE))
    return set(email for email in emails if is_valid_email(email))

def get_domain_age(domain):
    """Fetch domain age using whois."""
    try:
        w = whois.whois(domain)
        if w.creation_date:
            creation_date = w.creation_date[0] if isinstance(w.creation_date, list) else w.creation_date
            age = (pd.Timestamp.now() - pd.Timestamp(creation_date)).days // 365
            return f"{age} years" if age > 0 else "Less than a year"
        return "Unknown"
    except Exception as e:
        print(f"WHOIS error for {domain}: {e}")
        return "Unknown"

async def find_clickable_contact_links(page, base_url):
    """Find clickable contact links on the page with improved logic."""
    try:
        links = await page.query_selector_all('a')
        contact_links = []
        for link in links:
            try:
                href = await link.get_attribute('href')
                text = await link.text_content()
                if not href:
                    continue
                text_matches = any(keyword in (text or '').lower() for keyword in CONTACT_PAGE)
                href_matches = any(keyword in href.lower() for keyword in CONTACT_PAGE)
                if text_matches or href_matches:
                    if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
                        continue
                    if not href.startswith(('http://', 'https://')):
                        href = urljoin(base_url, href)
                    if href != base_url and href != base_url + '/':
                        contact_links.append(href)
            except Exception as e:
                print(f"Error processing link: {e}")
                continue
        return list(set(contact_links))
    except Exception as e:
        print(f"Error finding contact links: {e}")
        return []

async def scrape_contact_page(page, contact_url):
    """Scrape a contact page for emails."""
    try:
        await page.goto(contact_url, timeout=TIMEOUT/2, wait_until="domcontentloaded")
        content = await page.content()
        emails = extract_emails_from_text(content)
        return list(emails) if emails else None
    except Exception as e:
        print(f"Error scraping contact page {contact_url}: {e}")
        return None

async def fetch_with_playwright(url):
    """Fetch website content using Playwright with enhanced contact link detection."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                ignore_https_errors=True
            )
            page = await context.new_page()
            try:
                await page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
                content = await page.content()
                emails = extract_emails_from_text(content)
                contact_urls = await find_clickable_contact_links(page, url)
                for contact_url in contact_urls[:3]:
                    try:
                        contact_emails = await scrape_contact_page(page, contact_url)
                        if contact_emails:
                            emails.update(contact_emails)
                    except:
                        continue
                return {
                    'emails': list(emails) if emails else None,
                    'contact_url': contact_urls[0] if contact_urls else None
                }
            finally:
                await browser.close()
    except Exception as e:
        print(f"Playwright error for {url}: {e}")
        return {'emails': None, 'contact_url': None}

def fetch_with_requests(url):
    """Quick email check using requests."""
    try:
        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )
        return {
            'emails': extract_emails_from_text(response.text),
            'contact_url': None
        }
    except Exception as e:
        print(f"Requests error for {url}: {e}")
        return {'emails': None, 'contact_url': None}

async def extract_emails(url):
    """Hybrid email extraction with separate email and contact URL handling."""
    if not url.startswith(('http://', 'https://')):
        url = f'http://{url}'
    domain = url.split('//')[-1].split('/')[0]
    domain_age = get_domain_age(domain)
    result = fetch_with_requests(url)
    contact_urls = []
    if not result['emails']:
        playwright_result = await fetch_with_playwright(url)
        result['emails'] = playwright_result['emails']
        contact_urls = [playwright_result['contact_url']] if playwright_result['contact_url'] else []
    else:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                ignore_https_errors=True
            )
            page = await context.new_page()
            try:
                await page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
                contact_urls = await find_clickable_contact_links(page, url)
            finally:
                await browser.close()
    email_value = ', '.join(result['emails']) if result['emails'] else "No Email"
    contact_value = contact_urls[0] if contact_urls else "No Contact"
    return url, email_value, contact_value, domain_age, bool(result['emails']), bool(contact_urls)

async def process_excel(file_path):
    """Process Excel file with optimized parallel processing."""
    try:
        df = pd.read_excel(file_path)
        df.columns = [col.strip().lower() for col in df.columns]
        if 'website' not in df.columns:
            df.rename(columns={df.columns[0]: 'website'}, inplace=True)
        if 'emails' not in df.columns:
            df['emails'] = 'No Email'
        if 'contact_url' not in df.columns:
            df['contact_url'] = 'No Contact'
        if 'domain age' not in df.columns:
            df['domain age'] = 'N/A'
        urls = df['website'].astype(str).tolist()
        results = await asyncio.gather(*[extract_emails(url) for url in urls], return_exceptions=True)
        stats = {
            'total': len(results),
            'emails_found': 0,
            'contact_pages': 0,
            'no_contact': 0
        }
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error processing URL {urls[idx]}: {result}")
                df.loc[df['website'] == urls[idx], 'emails'] = "Error"
                df.loc[df['website'] == urls[idx], 'contact_url'] = "No Contact"
                df.loc[df['website'] == urls[idx], 'domain age'] = "N/A"
                stats['no_contact'] += 1
                continue
            url, email_value, contact_value, domain_age, has_email, has_contact = result
            df.loc[df['website'] == url, 'emails'] = email_value
            df.loc[df['website'] == url, 'contact_url'] = contact_value
            df.loc[df['website'] == url, 'domain age'] = domain_age
            if has_email:
                stats['emails_found'] += 1
            if has_contact:
                stats['contact_pages'] += 1
            else:
                stats['no_contact'] += 1
        df.to_excel(file_path, index=False)
        return file_path, stats
    except Exception as e:
        print(f"Excel processing error: {e}")
        return None, None