import re
import os
import asyncio
import requests
import whois # type: ignore
from playwright.async_api import async_playwright # type: ignore
import pandas as pd # type: ignore
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing

EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
TIMEOUT = 100000
MAX_WORKERS = multiprocessing.cpu_count() * 2  # Optimal worker count

def extract_emails_from_text(text):
    """Extract emails using regex."""
    return set(re.findall(EMAIL_PATTERN, text))


def get_domain_age(domain):
    """Fetch domain age using whois."""
    try:
        w = whois.whois(domain)
        if w.creation_date:
            # Handle case where creation_date is a list
            creation_date = w.creation_date[0] if isinstance(w.creation_date, list) else w.creation_date
            age = (pd.Timestamp.now() - pd.Timestamp(creation_date)).days // 365
            return f"{age} years" if age > 0 else "Less than a year"
        return "Unknown"
    except Exception as e:
        print(f"WHOIS error for {domain}: {e}")
        return "Unknown"


async def fetch_with_playwright(url):
    """Fetch website content using Playwright."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                ignore_https_errors=True,
                java_script_enabled=True
            )
            page = await context.new_page()
            try:
                await page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
                content = await page.content()
                emails = extract_emails_from_text(content)
                
                # Check common subpages
                subpages = ['contact', 'about', 'support', 'help', 'contact-us', 'mailto']
                links = await page.query_selector_all('a')
                for link in links:
                    href = await link.get_attribute('href')
                    if href and any(sub in href.lower() for sub in subpages):
                        try:
                            if not href.startswith(('http://', 'https://')):
                                if href.startswith('/'):
                                    href = f"{url.rstrip('/')}{href}"
                                else:
                                    href = f"{url.rstrip('/')}/{href}"
                            await page.goto(href, timeout=TIMEOUT, wait_until="domcontentloaded")
                            emails.update(extract_emails_from_text(await page.content()))
                        except Exception as e:
                            print(f"Error fetching subpage {href}: {e}")
                return list(emails) if emails else ["No email found"]
            finally:
                await browser.close()
    except Exception as e:
        print(f"Playwright error for {url}: {e}")
        return ["No email found"]


def fetch_with_requests(url):
    """Fetch website content using requests."""
    try:
        response = requests.get(
            url,
            timeout=TIMEOUT / 1000,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )
        return extract_emails_from_text(response.text)
    except Exception as e:
        print(f"Requests error for {url}: {e}")
        return set()


async def extract_emails(url):
    """Hybrid email extraction with domain age lookup."""
    if not url.startswith(('http://', 'https://')):
        url = f'http://{url}'
    domain = url.split('//')[-1].split('/')[0]
    domain_age = get_domain_age(domain)
    
    # First try with requests (faster)
    emails = fetch_with_requests(url)
    if not emails:
        # Fall back to Playwright if requests fails
        emails = await fetch_with_playwright(url)
    
    return url, ', '.join(emails) if emails else "No email found", domain_age


async def process_excel(file_path):
    """Process Excel file with multiprocessing for speed."""
    try:
        df = pd.read_excel(file_path)
        
        # Ensure proper column names
        if 'Emails' not in df.columns:
            df['Emails'] = ''
        if 'Domain Age' not in df.columns:
            df['Domain Age'] = ''
        if 'Website' not in df.columns:
            df.rename(columns={df.columns[0]: 'Website'}, inplace=True)

        # Process URLs using multiprocessing
        urls = df['Website'].astype(str).tolist()
        loop = asyncio.get_event_loop()
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = await asyncio.gather(*[
                loop.run_in_executor(executor, asyncio.run, extract_emails(url))
                for url in urls
            ])
        
        # Update DataFrame
        for url, emails, age in results:
            df.loc[df['Website'] == url, 'Emails'] = emails
            df.loc[df['Website'] == url, 'Domain Age'] = age
        
        # Save back to the same file
        df.to_excel(file_path, index=False)
        return file_path
    except Exception as e:
        print(f"Error processing Excel file: {e}")
        return None
