import re
import os
import asyncio
import requests
import whois
from playwright.async_api import async_playwright
import pandas as pd
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import urljoin, urlparse
from functools import lru_cache
import logging
import validators

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
TIMEOUT = 30000  # 30 seconds
BATCH_SIZE = 50  # Process URLs in batches
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

@lru_cache(maxsize=1000)
def get_domain_age(domain):
    """Fetch domain age using whois with caching."""
    try:
        w = whois.whois(domain)
        if w.creation_date:
            creation_date = w.creation_date[0] if isinstance(w.creation_date, list) else w.creation_date
            age = (pd.Timestamp.now() - pd.Timestamp(creation_date)).days // 365
            return f"{age} years" if age > 0 else "Less than a year"
        return "Unknown"
    except Exception as e:
        logging.error(f"WHOIS error for {domain}: {e}")
        return "Unknown"

async def find_clickable_contact_links(page, base_url):
    """Find clickable contact links on the page."""
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
                logging.error(f"Error processing link: {e}")
                continue
        return list(set(contact_links))
    except Exception as e:
        logging.error(f"Error finding contact links: {e}")
        return []

async def scrape_contact_page(page, contact_url):
    """Scrape a contact page for emails."""
    try:
        await page.goto(contact_url, timeout=TIMEOUT, wait_until="domcontentloaded")
        content = await page.content()
        emails = extract_emails_from_text(content)
        return list(emails) if emails else None
    except Exception as e:
        logging.error(f"Error scraping contact page {contact_url}: {e}")
        return None

async def fetch_with_playwright(url, browser):
    """Fetch website content using Playwright."""
    try:
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
            await context.close()
    except Exception as e:
        logging.error(f"Playwright error for {url}: {e}")
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
        logging.error(f"Requests error for {url}: {e}")
        return {'emails': None, 'contact_url': None}

def clean_url(url):
    """Clean and validate URL."""
    url = url.strip()
    # Remove any invalid characters
    url = re.sub(r'[^\x00-\x7F]+', '', url)
    # Remove leading/trailing spaces or invalid chars
    url = url.strip(' /\\')
    if not url:
        return None
    # Validate URL format
    if not validators.domain(url) and not validators.url(url):
        return None
    return url

async def try_url_with_protocols(original_url, browser):
    """Try URL with both http and https protocols."""
    cleaned_url = clean_url(original_url)
    if not cleaned_url:
        return original_url, "Error: Invalid URL", "No Contact", "N/A", False, False

    protocols = ['https://', 'http://']
    result = {'emails': None, 'contact_url': None}
    domain = urlparse(cleaned_url).netloc or cleaned_url
    domain_age = get_domain_age(domain)

    for protocol in protocols:
        url = protocol + cleaned_url if not cleaned_url.startswith(('http://', 'https://')) else cleaned_url
        # Try requests first for speed
        result = fetch_with_requests(url)
        if result['emails']:
            break
        # If no emails found, try playwright
        result = await fetch_with_playwright(url, browser)
        if result['emails']:
            break

    email_value = ', '.join(result['emails']) if result['emails'] else "No Email"
    contact_value = result['contact_url'] if result['contact_url'] else "No Contact"
    return original_url, email_value, contact_value, domain_age, bool(result['emails']), bool(result['contact_url'])

async def process_batch(urls, browser):
    """Process a batch of URLs."""
    return await asyncio.gather(*[try_url_with_protocols(url, browser) for url in urls], return_exceptions=True)

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
        stats = {
            'total': len(urls),
            'emails_found': 0,
            'contact_pages': 0,
            'no_contact': 0
        }
        
        results = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                # Process URLs in batches
                for i in range(0, len(urls), BATCH_SIZE):
                    batch_urls = urls[i:i + BATCH_SIZE]
                    batch_results = await process_batch(batch_urls, browser)
                    results.extend(batch_results)
                    logging.info(f"Processed batch {i // BATCH_SIZE + 1}/{len(urls) // BATCH_SIZE + 1}")
            finally:
                await browser.close()
        
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logging.error(f"Error processing URL {urls[idx]}: {result}")
                df.loc[df['website'] == urls[idx], 'emails'] = "Error"
                df.loc[df['website'] == urls[idx], 'contact_url'] = "No Contact"
                df.loc[df['website'] == urls[idx], 'domain age'] = "N/A"
                stats['no_contact'] += 1
                continue
            original_url, email_value, contact_value, domain_age, has_email, has_contact = result
            df.loc[df['website'] == original_url, 'emails'] = email_value
            df.loc[df['website'] == original_url, 'contact_url'] = contact_value
            df.loc[df['website'] == original_url, 'domain age'] = domain_age
            if has_email:
                stats['emails_found'] += 1
            if has_contact:
                stats['contact_pages'] += 1
            else:
                stats['no_contact'] += 1
        
        df.to_excel(file_path, index=False)
        return file_path, stats
    except Exception as e:
        logging.error(f"Excel processing error: {e}")
        return None, None