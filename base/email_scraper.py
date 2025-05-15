import re
import os
import asyncio
import requests
from playwright.async_api import async_playwright # type: ignore
import pandas as pd # type: ignore
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing
from multiprocessing import Pool, cpu_count

EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
TIMEOUT = 100000  # 100 seconds
MAX_WORKERS = 20  # Optimal number of workers

def extract_emails_from_text(text):
    """Extract emails using regex."""
    return set(re.findall(EMAIL_PATTERN, text))

async def fetch_with_playwright(url):
    """Fetch website content using Playwright with enhanced features."""
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
                        except:
                            continue
                
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
            timeout=TIMEOUT/1000,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )
        return extract_emails_from_text(response.text)
    except Exception as e:
        print(f"Requests error for {url}: {e}")
        return set()

async def extract_emails(url):
    """Hybrid email extraction with fallback."""
    if not url.startswith(('http://', 'https://')):
        url = f'http://{url}'
    
    # First try with requests (faster)
    emails = fetch_with_requests(url)
    if not emails:
        # Fall back to Playwright if requests fails
        emails = await fetch_with_playwright(url)
    return list(emails) if emails else ["No email found"]

async def process_url(url):
    """Process a single URL with error handling."""
    try:
        emails = await extract_emails(url)
        return url, ', '.join(emails) if emails else "No email found"
    except Exception as e:
        print(f"Error processing {url}: {e}")
        return url, "Error"

async def process_excel(file_path):
    """Process Excel file with multiprocessing."""
    try:
        df = pd.read_excel(file_path)
        
        # Ensure proper column names
        if 'Emails' not in df.columns:
            df['Emails'] = ''
        if 'Website' not in df.columns:
            df.rename(columns={df.columns[0]: 'Website'}, inplace=True)
        
        # Process URLs with multiprocessing
        urls = df['Website'].astype(str).tolist()
        results = []
        
        # Process URLs in batches to avoid overwhelming the system
        batch_size = 10
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            batch_results = await asyncio.gather(*[process_url(url) for url in batch])
            results.extend(batch_results)
        
        # Update DataFrame
        for url, emails in results:
            df.loc[df['Website'] == url, 'Emails'] = emails
        
        # Save back to the same file
        df.to_excel(file_path, index=False)
        return file_path
        
    except Exception as e:
        print(f"Error processing Excel file: {e}")
        return None