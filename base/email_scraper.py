import re
import os
import asyncio
import requests
import whois # type: ignore
from playwright.async_api import async_playwright # type: ignore
import pandas as pd # type: ignore
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from urllib.parse import urljoin

# Constants
EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
TIMEOUT = 100000  # 100 seconds
MAX_WORKERS = multiprocessing.cpu_count() * 2
CONTACT_KEYWORDS = ['contact', 'about', 'support', 'help', 'mailto', 'reach', 'connect']
CONTACT_PAGE = [ 'contact', 'contact-us', 'contactus']

def is_valid_email(email):
    """Validate email to exclude dummy, test, or file-like patterns."""
    # Common dummy/test email patterns
    dummy_patterns = [
        r'^demo@', r'^test@', r'^example@', r'^sample@',
        r'@example\.com$', r'@test\.com$', r'@demo\.com$'
    ]
    
    # File-like or JavaScript-related patterns
    file_patterns = [
        r'\.js$', r'\.png$', r'\.jpg$', r'\.jpeg$', r'\.gif$', r'\.css$',
        r'react-jsx-runtime@', r'react-dom@', r'react@', r'react-dom-client@',
        r'react-jsx-dev-runtime@'
    ]
    
    # Combine all invalid patterns
    invalid_patterns = dummy_patterns + file_patterns
    
    # Check if email matches any invalid pattern
    for pattern in invalid_patterns:
        if re.search(pattern, email, re.IGNORECASE):
            return False
    
    # Basic validation for realistic email structure
    # Ensure local part and domain are not empty or overly suspicious
    local, domain = email.split('@')
    if not local or not domain:
        return False
    
    # Allow emails that resemble website names (e.g., name@yourcompany.co)
    # Basic check for valid domain structure
    if not re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', domain):
        return False
    
    return True

def extract_emails_from_text(text):
    """Extract and validate emails using regex."""
    emails = set(re.findall(EMAIL_PATTERN, text, re.IGNORECASE))
    # Filter emails through validation
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
        # Get all links on the page
        links = await page.query_selector_all('a')
        contact_links = []
        
        for link in links:
            try:
                href = await link.get_attribute('href')
                text = await link.text_content()
                
                if not href:
                    continue
                    
                # Check if link text or href contains contact keywords
                text_matches = any(keyword in (text or '').lower() for keyword in CONTACT_PAGE)
                href_matches = any(keyword in href.lower() for keyword in CONTACT_PAGE)
                
                if text_matches or href_matches:
                    # Skip mailto links and non-web URLs
                    if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
                        continue
                        
                    # Make absolute URL if relative
                    if not href.startswith(('http://', 'https://')):
                        href = urljoin(base_url, href)
                    
                    # Verify the link is not the same as current page
                    if href != base_url and href != base_url + '/':
                        contact_links.append(href)
                        
            except Exception as e:
                print(f"Error processing link: {e}")
                continue
        
        # Return unique links only
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
                # First try main page
                await page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
                content = await page.content()
                emails = extract_emails_from_text(content)
                
                # If no emails found, check contact links
                contact_urls = []
                if not emails:
                    # Find all potential contact links
                    contact_urls = await find_clickable_contact_links(page, url)
                    
                    # Try each contact link for emails
                    for contact_url in contact_urls[:3]:  # Limit to top 3 contact links
                        try:
                            contact_emails = await scrape_contact_page(page, contact_url)
                            if contact_emails:
                                emails.update(contact_emails)
                                break  # Stop at first successful contact page
                        except:
                            continue
                
                # Prepare result
                result = {
                    'emails': list(emails) if emails else None,
                    'contact_url': contact_urls[0] if not emails and contact_urls else None
                }
                
                return result
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
            'contact_url': None  # Can't reliably find contact page with requests
        }
    except Exception as e:
        print(f"Requests error for {url}: {e}")
        return {'emails': None, 'contact_url': None}

async def extract_emails(url):
    """Hybrid email extraction with enhanced contact page fallback."""
    if not url.startswith(('http://', 'https://')):
        url = f'http://{url}'
    
    domain = url.split('//')[-1].split('/')[0]
    domain_age = get_domain_age(domain)
    
    # First try with requests (faster)
    result = fetch_with_requests(url)
    
    # Fall back to Playwright if no emails found
    if not result['emails']:
        playwright_result = await fetch_with_playwright(url)
        result['emails'] = playwright_result['emails']
        result['contact_url'] = playwright_result['contact_url']
    
    # Prepare final display value
    if result['emails']:
        display_value = ', '.join(result['emails'])
    elif result['contact_url']:
        display_value = result['contact_url']
    else:
        display_value = "No Email No Contact"
    
    return url, display_value, domain_age, bool(result['emails']), bool(result['contact_url'])

async def process_excel(file_path):
    """Process Excel file with optimized parallel processing."""
    try:
        df = pd.read_excel(file_path)
        
        # Standardize columns
        df.columns = [col.strip().lower() for col in df.columns]
        if 'website' not in df.columns:
            df.rename(columns={df.columns[0]: 'website'}, inplace=True)
        
        # Initialize columns if not exists
        if 'emails' not in df.columns:
            df['emails'] = 'No Email No Contact'
        if 'domain age' not in df.columns:
            df['domain age'] = 'N/A'

        # Process URLs in parallel
        urls = df['website'].astype(str).tolist()
        
        # Run extract_emails for each URL concurrently
        results = await asyncio.gather(*[extract_emails(url) for url in urls], return_exceptions=True)
        
        # Update statistics
        stats = {
            'total': len(results),
            'emails_found': 0,
            'contact_pages': 0,
            'no_contact': 0
        }
        
        # Update DataFrame
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error processing URL {urls[idx]}: {result}")
                df.loc[df['website'] == urls[idx], 'emails'] = "Error"
                df.loc[df['website'] == urls[idx], 'domain age'] = "N/A"
                stats['no_contact'] += 1
                continue
                
            url, display_value, domain_age, has_email, has_contact = result
            df.loc[df['website'] == url, 'emails'] = display_value
            df.loc[df['website'] == url, 'domain age'] = domain_age
            
            if has_email:
                stats['emails_found'] += 1
            elif has_contact:
                stats['contact_pages'] += 1
            else:
                stats['no_contact'] += 1
        
        # Save results
        df.to_excel(file_path, index=False)
        return file_path, stats
        
    except Exception as e:
        print(f"Excel processing error: {e}")
        return None, None