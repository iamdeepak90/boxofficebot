"""
common.py - ALL shared utilities and functions
"""

import sys
import os
import redis
import requests
import json
import logging
import time
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from fuzzywuzzy import fuzz
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# ============================================================================
# REDIS CONNECTION
# ============================================================================

REDIS_HOST = "ahmd8hlfkbzrlcwfmf7nek7p"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_USERNAME = "default"
REDIS_PASSWORD = "gAXXSKKvbIEgBpSkbfge8TAZmZ0TAfVhJudT3KeAykQkeLl1bUw7O5FNYSw9IiQt"

try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        username=REDIS_USERNAME,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=45,
    )
    redis_client.ping()
    logger.info(f"✅ Redis connected successfully to {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    logger.error(f"❌ Redis connection failed: {e}")
    redis_client = None

# ============================================================================
# REDIS SETTINGS
# ============================================================================

def get_setting(key: str, default: Any = None) -> Any:
    """Get setting from Redis"""
    try:
        if not redis_client:
            return default
        value = redis_client.get(f"settings:{key}")
        if value is None:
            return default
        return json.loads(value)
    except Exception as e:
        logger.error(f"Error getting setting {key}: {e}")
        return default

def set_setting(key: str, value: Any):
    """Set setting in Redis"""
    try:
        if redis_client:
            redis_client.set(f"settings:{key}", json.dumps(value))
    except Exception as e:
        logger.error(f"Error setting {key}: {e}")

# ============================================================================
# REDIS QUEUE
# ============================================================================

def enqueue_job(queue_name: str, job_data: Dict):
    """Add job to Redis queue"""
    try:
        if redis_client:
            redis_client.rpush(queue_name, json.dumps(job_data))
            logger.info(f"Job enqueued to {queue_name}")
    except Exception as e:
        logger.error(f"Error enqueueing job: {e}")

def dequeue_job(queue_name: str, timeout: int = 30) -> Optional[Dict]:
    """Get job from Redis queue (blocking)"""
    try:
        if not redis_client:
            time.sleep(timeout)
            return None
        result = redis_client.blpop(queue_name, timeout=timeout)
        if result:
            job_data = json.loads(result[1])
            return job_data
        return None
    except Exception as e:
        logger.error(f"Error dequeuing job: {e}")
        return None

def store_failed_job(job_data: Dict):
    """Store failed job for retry"""
    try:
        if redis_client:
            redis_client.rpush('queue:failed_jobs', json.dumps(job_data))
    except Exception as e:
        logger.error(f"Error storing failed job: {e}")

def get_failed_jobs() -> List[Dict]:
    """Get all failed jobs"""
    try:
        if not redis_client:
            return []
        jobs = []
        while True:
            result = redis_client.lpop('queue:failed_jobs')
            if not result:
                break
            jobs.append(json.loads(result))
        return jobs
    except Exception as e:
        logger.error(f"Error getting failed jobs: {e}")
        return []

# ============================================================================
# HTTP REQUESTS WITH RETRY
# ============================================================================

def request_with_retry(method: str, url: str, max_retries: int = 3, **kwargs) -> Optional[requests.Response]:
    """HTTP request with exponential backoff retry — retries on 5xx/network errors only"""
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.request(method, url, timeout=30, **kwargs)

            if response.status_code < 500:
                # 2xx/3xx = success, 4xx = bad request (no point retrying, return for caller to handle)
                if response.status_code >= 400:
                    logger.warning(f"Request failed (attempt {attempt}/{max_retries}): "
                                   f"HTTP {response.status_code} for url: {url} | {response.text[:500]}")
                return response

            # 5xx = server error, worth retrying
            logger.warning(f"Request failed (attempt {attempt}/{max_retries}): "
               f"HTTP {response.status_code} for url: {url} | {response.text[:500]}")

        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed (attempt {attempt}/{max_retries}): {e}")

        if attempt < max_retries:
            time.sleep(2 ** attempt)

    logger.error(f"Max retries reached for {url}")
    return None

# ============================================================================
# DIRECTUS API
# ============================================================================

def directus_get(endpoint: str) -> Dict:
    """GET request to Directus"""
    try:
        base_url = get_setting('directus_url', 'https://admin.boxofficetalk.com')
        token = get_setting('directus_token', '')
        
        url = f"{base_url}{endpoint}"
        headers = {}
        if token:
            headers['Authorization'] = f"Bearer {token}"
        
        response = request_with_retry('GET', url, headers=headers)
        if response:
            return response.json()
        return {'data': None}
    except Exception as e:
        logger.error(f"Directus GET error: {e}")
        return {'data': None}

def directus_post(endpoint: str, data: Dict) -> Dict:
    """POST request to Directus"""
    try:
        base_url = get_setting('directus_url', 'https://admin.boxofficetalk.com')
        token = get_setting('directus_token', '')
        
        url = f"{base_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f"Bearer {token}"
        
        response = request_with_retry('POST', url, headers=headers, json=data)
        if response:
            return response.json()
        return {'data': None}
    except Exception as e:
        logger.error(f"Directus POST error: {e}")
        return {'data': None}

def directus_patch(endpoint: str, data: Dict) -> Dict:
    """PATCH request to Directus"""
    try:
        base_url = get_setting('directus_url', 'https://admin.boxofficetalk.com')
        token = get_setting('directus_token', '')
        
        url = f"{base_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f"Bearer {token}"
        
        response = request_with_retry('PATCH', url, headers=headers, json=data)
        if response:
            return response.json()
        return {'data': None}
    except Exception as e:
        logger.error(f"Directus PATCH error: {e}")
        return {'data': None}

def directus_delete(endpoint: str) -> bool:
    """DELETE request to Directus"""
    try:
        base_url = get_setting('directus_url', 'https://admin.boxofficetalk.com')
        token = get_setting('directus_token', '')
        
        url = f"{base_url}{endpoint}"
        headers = {}
        if token:
            headers['Authorization'] = f"Bearer {token}"
        
        response = request_with_retry('DELETE', url, headers=headers)
        return response is not None
    except Exception as e:
        logger.error(f"Directus DELETE error: {e}")
        return False

def upload_file_to_directus(file_url: str = None, title: str = None) -> Optional[str]:
    """Upload file to Directus — downloads image first to bypass CDN hotlink protection."""
    if not file_url:
        return None

    base_url = get_setting('directus_url', 'https://admin.boxofficetalk.com')
    token = get_setting('directus_token', '')
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    for attempt in range(1, 4):
        try:
            # Download image locally first (avoids Directus /files/import hitting CDN blocks)
            img_response = requests.get(file_url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })

            # Don't retry on 404 — image doesn't exist or is geo-blocked
            if img_response.status_code == 404:
                logger.warning(f"Image not found (404): {file_url}")
                return None

            img_response.raise_for_status()

            content_type = img_response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            filename = f"{title or 'image'}.jpg"

            # Use MultipartEncoder for reliable Directus 10.x multipart upload
            try:
                from requests_toolbelt.multipart.encoder import MultipartEncoder
                multipart_data = MultipartEncoder(fields={
                    'title': (title or 'image')[:255],
                    'file': (filename, img_response.content, content_type)
                })
                upload_headers = {**headers, 'Content-Type': multipart_data.content_type}
                resp = requests.post(
                    f"{base_url}/files",
                    headers=upload_headers,
                    data=multipart_data,
                    timeout=60
                )
            except ImportError:
                # Fallback to standard multipart if requests_toolbelt not installed
                files = {"file": (filename, img_response.content, content_type)}
                resp = requests.post(
                    f"{base_url}/files",
                    headers=headers,
                    files=files,
                    data={"title": (title or "image")[:255]},
                    timeout=60
                )

            if resp.status_code >= 400:
                logger.warning(f"Directus upload failed (attempt {attempt}/3, status {resp.status_code}): {resp.text[:500]}")
                time.sleep(3 * attempt)
                continue

            file_id = resp.json().get("data", {}).get("id")
            if file_id:
                logger.info(f"Image uploaded: {file_url[:80]} -> {file_id}")
                return str(file_id)

            logger.warning(f"Upload returned no file ID: {resp.text[:300]}")
            return None

        except Exception as e:
            logger.error(f"Upload attempt {attempt}/3 failed: {e}")
            time.sleep(3 * attempt)

    return None

# ============================================================================
# OPENROUTER API
# ============================================================================

def call_openrouter(model: str, prompt: str, temperature: float = 0.7, max_tokens: int = 4000, system_prompt: str = None) -> Optional[str]:
    """Call OpenRouter API"""
    try:
        api_key = get_setting('openrouter_api_key', '')
        if not api_key:
            logger.error("OpenRouter API key not set")
            return None
        
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        response = request_with_retry('POST', url, headers=headers, json=data)
        
        if response:
            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            return content
        
        return None
        
    except Exception as e:
        logger.error(f"OpenRouter API error: {e}")
        return None

def call_openrouter_image(model: str, prompt: str, width: int = 1024, height: int = 768) -> Optional[str]:
    """Call OpenRouter image generation"""
    try:
        api_key = get_setting('openrouter_api_key', '')
        if not api_key:
            return None
        
        url = "https://openrouter.ai/api/v1/images/generations"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "prompt": prompt,
            "width": width,
            "height": height
        }
        
        response = request_with_retry('POST', url, headers=headers, json=data)
        
        if response:
            result = response.json()
            image_url = result.get('data', [{}])[0].get('url', '')
            return image_url
        
        return None
        
    except Exception as e:
        logger.error(f"OpenRouter image error: {e}")
        return None

# ============================================================================
# TAVILY SEARCH
# ============================================================================

def tavily_search(query: str, max_results: int = 5) -> List[Dict]:
    """Search using Tavily API"""
    try:
        api_key = get_setting('tavily_api_key', '')
        if not api_key:
            logger.error("Tavily API key not set")
            return []
        
        url = "https://api.tavily.com/search"
        
        data = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results
        }
        
        response = request_with_retry('POST', url, json=data)
        
        if response:
            result = response.json()
            return result.get('results', [])
        
        return []
        
    except Exception as e:
        logger.error(f"Tavily search error: {e}")
        return []

# ============================================================================
# SLACK API
# ============================================================================

def slack_post_message(blocks: List[Dict], text: str) -> Optional[Dict]:
    """Post message to Slack"""
    try:
        bot_token = get_setting('slack_bot_token', '')
        channel_id = get_setting('slack_channel_id', '')
        
        if not bot_token or not channel_id:
            logger.warning("Slack credentials not set")
            return None
        
        url = "https://slack.com/api/chat.postMessage"
        
        headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json"
        }
        
        data = {
            "channel": channel_id,
            "blocks": blocks,
            "text": text
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        result = response.json()
        
        if result.get('ok'):
            logger.info("Slack message posted")
            return result
        else:
            logger.error(f"Slack error: {result.get('error')}")
            return None
            
    except Exception as e:
        logger.error(f"Slack post error: {e}")
        return None

def slack_delete_message(channel: str, timestamp: str) -> bool:
    """Delete Slack message"""
    try:
        bot_token = get_setting('slack_bot_token', '')
        if not bot_token:
            return False
        
        url = "https://slack.com/api/chat.delete"
        
        headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json"
        }
        
        data = {
            "channel": channel,
            "ts": timestamp
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        result = response.json()
        
        return result.get('ok', False)
        
    except Exception as e:
        logger.error(f"Slack delete error: {e}")
        return False

def slack_ephemeral(response_url: str, text: str):
    """Send ephemeral message to Slack"""
    try:
        data = {
            "text": text,
            "response_type": "ephemeral"
        }
        requests.post(response_url, json=data, timeout=10)
    except Exception as e:
        logger.error(f"Slack ephemeral error: {e}")

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def slugify(text: str) -> str:
    """Convert text to URL-friendly slug"""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text[:200]

def fuzzy_match(text1: str, text2: str) -> int:
    """Return fuzzy match score (0-100)"""
    return fuzz.ratio(text1.lower(), text2.lower())

def calculate_day_number(release_date: str, current_date: str) -> int:
    """Calculate day number from release date"""
    release = datetime.strptime(release_date, "%Y-%m-%d")
    current = datetime.strptime(current_date, "%Y-%m-%d")
    return (current - release).days + 1

def parse_number_from_text(text: str) -> Optional[float]:
    """Extract number from text (handles Cr, Lakh, K)"""
    try:
        text = text.replace(',', '').replace('₹', '').strip()
        
        # Extract number
        match = re.search(r'(\d+\.?\d*)', text)
        if not match:
            return None
        
        num = float(match.group(1))
        
        # Handle units
        text_lower = text.lower()
        if 'cr' in text_lower or 'crore' in text_lower:
            return num
        elif 'lakh' in text_lower or 'lac' in text_lower:
            return num / 100
        elif 'k' in text_lower or 'thousand' in text_lower:
            return num / 100000
        else:
            return num
            
    except Exception as e:
        logger.error(f"Number parse error: {e}")
        return None

def extract_json_from_text(text: str) -> Optional[Dict]:
    """Extract JSON from text (handles markdown code blocks)"""
    try:
        # Remove markdown code blocks
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()
        
        # Find JSON object
        start = text.find('{')
        end = text.rfind('}') + 1
        
        if start != -1 and end > start:
            json_str = text[start:end]
            return json.loads(json_str)
        
        return None
        
    except Exception as e:
        logger.error(f"JSON extract error: {e}")
        return None

def log_job_start(job_type: str, job_data: Dict):
    """Log job start"""
    logger.info(f"{'='*60}")
    logger.info(f"JOB START: {job_type}")
    logger.info(f"Data: {json.dumps(job_data, indent=2)}")
    logger.info(f"{'='*60}")

def log_job_complete(job_type: str):
    """Log job completion"""
    logger.info(f"✅ JOB COMPLETE: {job_type}")

def log_job_failed(job_type: str, error: str):
    """Log job failure"""
    logger.error(f"❌ JOB FAILED: {job_type} - {error}")


# ============================================================================
# PLAYWRIGHT SCRAPING
# ============================================================================

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not available, using requests fallback")

def get_page_content(url: str) -> Optional[str]:
    """Fetch page content with Playwright (fallback to requests)"""
    if PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                proxies = get_setting("scraper_proxies", [])
                proxy_config = {"server": proxies[0]} if proxies else None
                
                browser = p.chromium.launch(
                    headless=True,
                    args=['--disable-blink-features=AutomationControlled']
                )
                
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    proxy=proxy_config
                )
                
                page = context.new_page()
                
                # Increased timeout + faster wait strategy
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                page.wait_for_timeout(2000)
                
                content = page.content()
                browser.close()
                
                return content
                
        except Exception as e:
            logger.error(f"Playwright failed: {e}")
    
    # Fallback to requests
    try:
        response = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"Requests failed: {e}")
        return None


def parse_box_office_table(html_content: str) -> Optional[Dict]:
    """
    Parse Sacnilk box office data.
    PRIMARY:  Individual day page — 'Overall Total India Net Collection' row
    FALLBACK: Movie page — sum Indian language sections per day (desktop cards only)
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # ── 1. Totals from "Total Collections Summary" section ────────────────
        totals = {}
        summary_h2 = soup.find('h2', string=lambda t: t and 'Total Collections Summary' in t)
        if summary_h2:
            parent = summary_h2.find_parent('section')
            if parent:
                # Only target the first grid (top 4 cards) — skip percentage breakdown grid
                first_grid = parent.find('div', class_=lambda c: c and 'grid' in c and 'gap-4' in c)
                if first_grid:
                    for card in first_grid.find_all('div', recursive=False):
                        label_el = card.find('div', class_=lambda c: c and 'text-gray-600' in c)
                        value_el = card.find('div', class_=lambda c: c and 'font-bold' in c)
                        if not label_el or not value_el:
                            # Also check <a> tags (Worldwide card is an <a>)
                            label_el = card.find('div', class_=lambda c: c and 'text-gray-600' in c)
                            value_el = card.find('div', class_=lambda c: c and 'font-bold' in c)
                        if not label_el or not value_el:
                            continue
                        label = label_el.get_text(strip=True).lower()
                        value = parse_number_from_text(value_el.get_text(strip=True))
                        if value is None:
                            continue
                        if 'india gross' in label:
                            totals['india_gross_total'] = value
                        elif 'overseas' in label:
                            totals['overseas_total'] = value
                        elif 'worldwide' in label:
                            totals['worldwide_total'] = value

        # Also check <a> Worldwide card separately (it's an <a> not a <div>)
        if 'worldwide_total' not in totals and summary_h2:
            parent = summary_h2.find_parent('section')
            if parent:
                worldwide_card = parent.find('a', class_=lambda c: c and 'collection-card' in c)
                if worldwide_card:
                    label_el = worldwide_card.find('div', class_=lambda c: c and 'text-gray-600' in c)
                    value_el = worldwide_card.find('div', class_=lambda c: c and 'font-bold' in c)
                    if label_el and value_el and 'worldwide' in label_el.get_text(strip=True).lower():
                        value = parse_number_from_text(value_el.get_text(strip=True))
                        if value:
                            totals['worldwide_total'] = value

        logger.info(f"Parsed totals: {totals}")

        # ── 2. Check if individual day page ───────────────────────────────────
        # Individual day page has "Overall Total India Net Collection" in yellow text
        days_data = []

        overall_el = soup.find(
            lambda tag: tag.name and
            'Overall Total India Net Collection' in tag.get_text() and
            any('text-yellow-300' in c for c in tag.get('class', []))
        )

        if overall_el:
            # Desktop rows only — class "hidden md:block"
            # Each row has grid-cols-4: Day | India Net (purple) | Shows | Occupancy
            for row in soup.select('div.hidden.md\\:block > div[class*="border-b"]'):
                day_el = row.find('div', class_=lambda c: c and 'font-bold' in c and 'text-gray-800' in c)
                net_el = row.find('div', class_=lambda c: c and 'text-purple-600' in c)
                if not day_el or not net_el:
                    continue
                day_match = re.search(r'Day\s*(\d+)', day_el.get_text())
                if not day_match:
                    continue
                day_number = int(day_match.group(1))
                india_net = parse_number_from_text(net_el.get_text(strip=True)) or 0
                if india_net > 0:
                    days_data.append({'day_number': day_number, 'india_net': india_net})

            if days_data:
                logger.info(f"[PRIMARY] Parsed {len(days_data)} days from individual day page")
                days_data.sort(key=lambda x: x['day_number'])
                return {'days': days_data, 'totals': totals}
            else:
                logger.warning("[PRIMARY] Day page detected but no rows parsed — falling back")

        # ── 3. FALLBACK: Movie page — sum Indian language sections ─────────────
        # FIX: Only select cards from language section grids, NOT from
        # any other grid on the page (e.g. chart/graph containers)
        # Each language section has id="collection-cards-N" on its grid div
        OVERSEAS_KEYWORDS = {'overseas', 'international', 'worldwide', 'foreign'}

        day_totals: Dict[int, float] = {}
        day_hrefs: Dict[int, str] = {}
        lang_count = 0

        for section in soup.find_all('section'):
            h2 = section.find('h2')
            if not h2:
                continue
            h2_text = h2.get_text(strip=True).lower()
            if 'daily net collection' not in h2_text:
                continue
            if any(kw in h2_text for kw in OVERSEAS_KEYWORDS):
                logger.info(f"Skipping section: {h2.get_text(strip=True)[:50]}")
                continue

            lang_count += 1

            # FIX: Only select the cards grid with id="collection-cards-N"
            # This avoids picking up duplicate cards from graph/chart containers
            cards_grid = section.find('div', id=lambda i: i and i.startswith('collection-cards-'))
            if not cards_grid:
                continue

            for card in cards_grid.select('a.collection-card[data-day]'):
                day_attr = card.get('data-day', '')
                if not day_attr.isdigit():
                    continue
                day_number = int(day_attr)

                amount_el = card.find('div', class_=lambda c: c and 'font-bold' in c)
                india_net = parse_number_from_text(amount_el.get_text(strip=True)) if amount_el else 0

                day_totals[day_number] = round(
                    day_totals.get(day_number, 0.0) + (india_net or 0), 2
                )

                if day_number not in day_hrefs:
                    href = card.get('href', '')
                    if href:
                        day_hrefs[day_number] = href

        for day_number, india_net in sorted(day_totals.items()):
            days_data.append({
                'day_number': day_number,
                'india_net': india_net,
                'day_page_href': day_hrefs.get(day_number, '')
            })

        logger.info(f"[FALLBACK] {lang_count} language sections, {len(days_data)} days summed")

        # ── 4. Fallback totals ─────────────────────────────────────────────────
        if 'india_gross_total' not in totals and days_data:
            fallback = round(sum(d['india_net'] for d in days_data), 2)
            if fallback > 0:
                totals['india_gross_total'] = fallback
                logger.info(f"Computed india_gross_total from daily sum: ₹{fallback} Cr")

        if not days_data and not totals:
            logger.error("parse_box_office_table: nothing parsed — check HTML selectors")
            return None

        return {'days': days_data, 'totals': totals}

    except Exception as e:
        logger.error(f"parse_box_office_table failed: {e}")
        return None

def scrape_sacnilk_movies(sacnilk_url: str) -> List[Dict]:
    """Scrape Sacnilk upcoming movies page"""
    try:
        html = get_page_content(sacnilk_url)
        
        if not html:
            return []
        
        soup = BeautifulSoup(html, "html.parser")
        movies = []

        container = soup.find("div", id="upcomingMoviesContainer")
        if not container:
            return []

        movie_cards = container.select("a[href^='/movie/']")

        for card in movie_cards:
            href = (card.get("href") or "").strip()
            if not href:
                continue

            title_tag = card.find("h3")
            title = title_tag.get_text(strip=True) if title_tag else None

            movies.append({
                "title": title,
                "sacnilk_source_url": urljoin("https://sacnilk.com", href),
                "slug": slugify(title) if title else None,  # slug will be updated with year after detail scrape
            })

        return movies
        
    except Exception as e:
        logger.error(f"Sacnilk upcoming scrape failed: {e}")
        return []


def scrape_movie_details(sacnilk_url: str) -> Optional[Dict]:
    """Scrape full movie details from Sacnilk"""
    try:
        html = get_page_content(sacnilk_url)
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        
        title = _extract_movie_title(soup)
        summary = _extract_summary(soup)
        poster = _extract_poster_url(soup)
        key_details = _extract_key_details(soup)
        release = _extract_release_information(soup)
        boxoffice = _extract_boxoffice_budget(soup)
        tags = _extract_tags(soup)
        cast_and_crew = _extract_cast_and_crew(soup)
        
        return {
            "title": title,
            "summary": summary,
            "poster": poster,
            "runtime": key_details["runtime"],
            "cbfc_rating": key_details["cbfc_rating"],
            "genre": key_details["genre"],
            "languages": key_details["languages"],
            "release_date": release["release_date"],
            "ott_platform": release["ott_platform"],
            "ott_release_date": release["ott_release_date"],
            "india_gross_total": boxoffice["india_gross_total"],
            "overseas_total": boxoffice["overseas_total"],
            "budget": boxoffice["budget"],
            "cast_and_crew": cast_and_crew,
            "tags": tags
        }
        
    except Exception as e:
        logger.error(f"Movie details scrape failed: {e}")
        return None


# Helper functions (add these after scrape_movie_details)

def _text(el: Optional[Tag]) -> Optional[str]:
    """Extract text from BeautifulSoup tag"""
    if not el:
        return None
    value = el.get_text(" ", strip=True)
    return value or "N/A"


def _runtime_to_minutes(runtime_text: str) -> Optional[int]:
    """Convert '3h 19m' -> 199, '150m' -> 150, '2h' -> 120"""
    if not runtime_text:
        return None
    
    hours = 0
    minutes = 0
    
    h_match = re.search(r"(\d+)\s*h", runtime_text, re.I)
    m_match = re.search(r"(\d+)\s*m", runtime_text, re.I)
    
    if h_match:
        hours = int(h_match.group(1))
    if m_match:
        minutes = int(m_match.group(1))
    
    total = hours * 60 + minutes
    return total if total > 0 else None


def _find_section_from_label(soup: BeautifulSoup, label_pattern: str) -> Optional[Tag]:
    pattern = re.compile(label_pattern, re.I)

    label_node = soup.find(string=pattern)

    if not label_node:
        for tag in soup.find_all(True):
            text = tag.get_text(" ", strip=True)
            if text and pattern.search(text):
                label_node = tag
                break

    if not label_node:
        return None

    current = label_node if isinstance(label_node, Tag) else label_node.parent
    fallback = None

    while current and isinstance(current, Tag):
        if current.name not in {"span", "b", "i", "strong", "small"}:
            fallback = current

        direct_children = current.find_all(recursive=False)
        li_count = len(current.find_all("li"))
        has_heading = current.find(["h1", "h2", "h3", "h4", "h5", "h6"]) is not None

        if li_count >= 1 or has_heading or len(direct_children) >= 3:
            return current

        current = current.parent

    return fallback

def _extract_movie_title(soup: BeautifulSoup) -> str:
    """
    Extract movie title from the main <h1>.
    Returns 'N/A' if not found.
    """
    h1 = soup.find("h1")
    if not h1:
        return "N/A"

    title = h1.get_text(" ", strip=True)
    return title or "N/A"

def _extract_summary(soup: BeautifulSoup) -> Optional[str]:
    """Extract movie summary"""
    section = _find_section_from_label(soup, r"Summary\s*Text")
    if section:
        p = section.find("p")
        if p:
            return _text(p)
    
    label_node = soup.find(string=re.compile(r"Summary\s*Text", re.I))
    if label_node:
        for nxt in label_node.parent.find_all_next(["p", "div"], limit=8):
            txt = _text(nxt)
            if txt and len(txt) > 40:
                return txt
    
    return None


def _extract_poster_url(soup: BeautifulSoup) -> str:
    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        if "movie" in src.lower():
            return src
    return "N/A"


def _normalize_label(text: str) -> str:
    """Normalize label text for case-insensitive, whitespace-safe matching."""
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_key_details(soup: BeautifulSoup) -> Dict:
    """Extract genre, runtime, CBFC, languages from Key Details section."""

    defaults = {
        "genre": "N/A",
        "runtime": 0,
        "cbfc_rating": "N/A",
        "languages": "N/A",
    }

    section = _find_section_from_label(soup, r"Key\s*Details")
    if not section:
        return defaults.copy()

    details = defaults.copy()

    # Only direct/relevant list items if possible
    for li in section.select("li"):
        spans = li.find_all("span")
        if len(spans) < 2:
            continue

        label = _normalize_label(_text(spans[0]))
        value = _text(spans[-1]).strip()

        if not label or not value:
            continue

        if "genre" in label:
            details["genre"] = value
        elif "runtime" in label:
            details["runtime"] = _runtime_to_minutes(value)
        elif "cbfc" in label:
            details["cbfc_rating"] = value
        elif "language" in label:
            details["languages"] = value

    return details


from datetime import datetime
from typing import Optional

def _parse_date(value: str) -> Optional[str]:
    """Convert any scraped date string to Directus-compatible YYYY-MM-DD"""
    if not value or value.strip().lower() in ("n/a", "not available", "-", ""):
        return None

    formats = [
        "%d %b %Y",     # 26 Mar 2026  ← your current format
        "%d %B %Y",     # 26 March 2026
        "%B %d, %Y",    # March 26, 2026
        "%b %d, %Y",    # Mar 26, 2026
        "%d-%m-%Y",     # 26-03-2026
        "%d/%m/%Y",     # 26/03/2026
        "%Y-%m-%d",     # 2026-03-26 (already correct)
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    logger.warning(f"Could not parse date: '{value}'")
    return None


def _extract_release_information(soup: BeautifulSoup) -> Dict:
    details = {
        "release_date": None,       # ← None instead of "N/A"
        "ott_platform": [],
        "ott_release_date": None,   # ← None instead of "N/A"
    }

    section = _find_section_from_label(soup, r"Release\s*Information")
    if not section:
        return details

    # 1) Theatrical release date
    for li in section.select("li"):
        spans = li.find_all("span")
        if len(spans) < 2:
            continue
        label = _normalize_label(_text(spans[0]))
        value = _text(spans[-1])
        if "theatrical release" in label:
            details["release_date"] = _parse_date(value)  # ← convert here
            break

    # 2) Find OTT block
    ott_li = None
    for li in section.select("li"):
        li_text = _normalize_label(_text(li))
        if "ott release" in li_text:
            ott_li = li
            break

    if not ott_li:
        return details

    # 3) Extract OTT platform(s)
    platform_names: List[str] = []

    for row in ott_li.select("div.flex.justify-between"):
        spans = row.find_all("span")
        if not spans:
            continue

        label = _normalize_label(_text(spans[0]))
        if "platform" not in label:
            continue

        for img in row.find_all("img"):
            name = (img.get("alt") or img.get("title") or "").strip()
            if name and name not in platform_names:
                platform_names.append(name)

        # fallback if platform appears as text instead of image
        if not platform_names and len(spans) > 1:
            fallback_text = _text(spans[-1])
            if fallback_text:
                platform_names.append(fallback_text)

        break

    details["ott_platform"] = ", ".join(platform_names) if platform_names else None

    # 4) Extract OTT release date
    for row in ott_li.select("div.flex.justify-between"):
        spans = row.find_all("span")
        if len(spans) < 2:
            continue
        label = _normalize_label(_text(spans[0]))
        value = _text(spans[-1])
        if label in {"release date", "release date:"}:
            details["ott_release_date"] = _parse_date(value)  # ← convert here
            break

    return details



def _extract_amount(value: str) -> float:
    """
    Extract numeric value only from strings like:
    '₹450.19 Cr' -> 450.19
    '₹175 Cr' -> 175.0
    """
    if not value:
        return 0.0

    value = value.replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else 0.0


def _extract_boxoffice_budget(soup: BeautifulSoup) -> Dict:
    """
    Extract from Quick Stats section:
    - total_gross
    - overseas
    - budget

    Returns numbers only, without ₹ or Cr.
    """

    details = {
        "india_gross_total": 0.0,
        "overseas_total": 0.0,
        "budget": 0.0,
    }

    section = _find_section_from_label(soup, r"Quick\s*Stats")
    if not section:
        return details

    for row in section.select("div.flex.justify-between"):
        spans = row.find_all("span")
        if len(spans) < 2:
            continue

        label = _normalize_label(_text(spans[0]))
        value = _text(spans[-1])

        if "total gross" in label:
            details["india_gross_total"] = _extract_amount(value)
        elif "overseas" in label:
            details["overseas_total"] = _extract_amount(value)
        elif "budget" in label:
            details["budget"] = _extract_amount(value)

    return details


def _extract_cast_and_crew(soup: BeautifulSoup) -> list:
    """Extract cast and crew - simple and working approach"""
    
    section = _find_section_from_label(soup, r"Cast\s*&?\s*Crew")
    if not section:
        logger.warning("Cast & Crew section not found")
        return []
    
    all_people = {}
    current_role = "Actor"  # Default to Actor
    
    # Find all elements in order
    for el in section.descendants:
        if not hasattr(el, 'name'):
            continue
        
        # Check for role headers (h4 with "Cast" or "Crew")
        if el.name == "h4":
            text = _text(el)
            if text:
                if "Cast" in text:
                    current_role = "Actor"
                    logger.info("Switched to Cast section")
                elif "Crew" in text:
                    current_role = "Crew"
                    logger.info("Switched to Crew section")
        
        # Extract person links
        if el.name == "a":
            href = el.get("href", "")
            if "/tag/" not in href:
                continue
            
            # Get text from span.truncate
            span = el.find("span", class_="truncate")
            text = _text(span) if span else _text(el)
            if not text:
                continue
            
            # Parse based on current section
            if current_role == "Actor":
                # Cast section: plain name
                name = text.strip()
                person_type = "Actor"
            else:
                # Crew section: "Role: Name" format
                if ":" in text:
                    parts = text.split(":", 1)
                    person_type = parts[0].strip()
                    name = parts[1].strip()
                else:
                    name = text.strip()
                    person_type = "Crew"
            
            # Validation
            if len(name) < 2 or len(name) > 100:
                continue
            
            name_lower = name.lower()
            sacnilk_url = urljoin("https://sacnilk.com", href)
            
            logger.info(f"Found: {name} ({person_type}) - {sacnilk_url}")
            
            # Add or merge
            if name_lower not in all_people:
                all_people[name_lower] = {
                    "name": name,
                    "slug": slugify(name),
                    "types": [person_type],
                    "sacnilk_url": sacnilk_url
                }
            else:
                if person_type not in all_people[name_lower]["types"]:
                    all_people[name_lower]["types"].append(person_type)
    
    logger.info(f"Total extracted: {len(all_people)} people")
    return list(all_people.values())


def _extract_tags(soup: BeautifulSoup) -> list:
    """Extract movie tags"""
    tags = []
    seen = set()
    
    for a in soup.find_all("a", class_="tag", href=True):
        name = _text(a)
        
        if not name:
            continue
        
        # Clean and validate
        name = name.strip()
        
        # Skip garbage
        if (
            len(name) < 2 or 
            len(name) > 50 or
            name.startswith(('http', '/', '#'))
        ):
            continue
        
        # Deduplicate
        name_lower = name.lower()
        if name_lower in seen:
            continue
        
        seen.add(name_lower)
        tags.append(name)
    
    return tags[:20]  # Max 20 tags

# ============================================================================
# MOVIE & PEOPLE HELPERS
# ============================================================================

def get_or_create_person(name: str, types: list, sacnilk_url: str = None) -> Optional[str]:
    """Get or create person in Directus"""
    try:
        if not name:
            return None
        
        # Check by sacnilk_url first
        if sacnilk_url:
            result = directus_get(f"/items/people?filter[sacnilk_url][_eq]={sacnilk_url}&limit=1")
            existing = result.get('data', [])
            
            if existing:
                person_id = existing[0]['id']
                existing_types = existing[0].get('type', []) or []
                
                updated_types = list(set(existing_types + types))
                if updated_types != existing_types:
                    directus_patch(f"/items/people/{person_id}", {'type': updated_types})
                
                return person_id
        
        # Check by name
        result = directus_get(f"/items/people?filter[name][_eq]={name}&limit=1")
        existing = result.get('data', [])
        
        if existing:
            person_id = existing[0]['id']
            existing_types = existing[0].get('type', []) or []
            
            update_data = {}
            updated_types = list(set(existing_types + types))
            
            if updated_types != existing_types:
                update_data['type'] = updated_types
            
            # Add sacnilk_url if missing
            if sacnilk_url and not existing[0].get('sacnilk_url'):
                update_data['sacnilk_url'] = sacnilk_url
            
            if update_data:
                directus_patch(f"/items/people/{person_id}", update_data)
            
            return person_id
        
        # Create new person
        person_data = {
            'name': name,
            'slug': slugify(name),
            'type': types,
            'status': 'published',
            'sacnilk_url': sacnilk_url  # ← MUST BE HERE
        }
        
        result = directus_post('/items/people', person_data)
        person_id = result.get('data', {}).get('id')
        
        if person_id:
            logger.info(f"Created person: {name} - {sacnilk_url}")
        
        return person_id
        
    except Exception as e:
        logger.error(f"Get/create person error: {e}")
        return None

def check_duplicate_movie(title: str, sacnilk_url: str) -> Optional[Dict]:
    """Check if movie already exists"""
    try:
        # Exact URL match
        result = directus_get(f"/items/movies?filter[sacnilk_source_url][_eq]={sacnilk_url}&limit=1")
        exact_match = result.get('data', [])
        
        if exact_match and len(exact_match) > 0:
            return exact_match[0]
        
        # Fuzzy title match — use Directus search to pre-filter candidates
        # instead of loading all 1000 movies into memory
        threshold = get_setting('fuzzy_match_threshold', 90)

        # Extract first 3 significant words for a targeted search
        search_term = ' '.join(title.split()[:3])
        result = directus_get(f"/items/movies?search={requests.utils.quote(search_term)}&limit=50&fields=id,title,sacnilk_source_url")
        candidates = result.get('data', [])

        for movie in candidates:
            similarity = fuzzy_match(title, movie.get('title', ''))
            if similarity >= threshold:
                return movie
        
        return None
        
    except Exception as e:
        logger.error(f"Duplicate check failed: {e}")
        return None

def send_duplicate_alert_slack(new_title: str, existing_title: str, similarity: int, new_url: str):
    """Send Slack alert for potential duplicate"""
    try:
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "⚠️ POTENTIAL DUPLICATE MOVIE"}
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*New:* {new_title}\n*Existing:* {existing_title}\n*Similarity:* {similarity}%\n*URL:* {new_url}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Create New"},
                        "style": "primary",
                        "value": new_url,
                        "action_id": "create_duplicate"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Skip"},
                        "style": "danger",
                        "value": new_url,
                        "action_id": "skip_duplicate"
                    }
                ]
            }
        ]
        
        slack_post_message(blocks, f"Duplicate: {new_title}")
        
    except Exception as e:
        logger.error(f"Duplicate alert failed: {e}")


# ============================================================================
# AI PIPELINE STAGES
# ============================================================================

def stage_generation(prompt: str, pipeline_type: str) -> Optional[str]:
    """
    Stage 1: Generate draft content
    pipeline_type: 'news', 'plot', 'daily', 'hub'
    """
    try:
        logger.info(f"STAGE 1: Generation ({pipeline_type})")
        
        # Select model based on pipeline type
        if pipeline_type == 'news':
            model = get_setting("news_generation_model", "deepseek/deepseek-v3.2")
            temperature = get_setting("news_generation_temperature", 0.7)
            max_tokens = get_setting("news_generation_max_tokens", 8000)
        elif pipeline_type == 'plot':
            model = get_setting("plot_generation_model", "deepseek/deepseek-v3.2")
            temperature = get_setting("plot_generation_temperature", 0.7)
            max_tokens = get_setting("plot_generation_max_tokens", 2000)
        elif pipeline_type == 'daily':
            model = get_setting("daily_generation_model", "deepseek/deepseek-v3.2")
            temperature = get_setting("daily_generation_temperature", 0.7)
            max_tokens = get_setting("daily_generation_max_tokens", 4000)
        elif pipeline_type == 'hub':
            model = get_setting("hub_generation_model", "deepseek/deepseek-v3.2")
            temperature = get_setting("hub_generation_temperature", 0.7)
            max_tokens = get_setting("hub_generation_max_tokens", 4000)
        else:
            raise ValueError(f"Unknown pipeline type: {pipeline_type}")
        
        result = call_openrouter(model, prompt, temperature, max_tokens)
        
        if not result:
            fallback_model = get_setting("fallback_generation_model", "openai/gpt-4-turbo")
            logger.warning(f"Primary model failed, trying fallback: {fallback_model}")
            result = call_openrouter(fallback_model, prompt, temperature, max_tokens)
        
        return result
        
    except Exception as e:
        logger.error(f"Generation stage failed: {e}")
        return None


def stage_humanize(draft_content: str, pipeline_type: str) -> Optional[str]:
    """
    Stage 2: Humanize content
    pipeline_type: 'news', 'plot', 'daily', 'hub'
    """
    try:
        logger.info(f"STAGE 2: Humanization ({pipeline_type})")
        
        if pipeline_type == 'news':
            model = get_setting("news_humanize_model", "deepseek/deepseek-v3.2")
            temperature = get_setting("news_humanize_temperature", 0.8)
            max_tokens = get_setting("news_humanize_max_tokens", 8000)
        elif pipeline_type == 'plot':
            model = get_setting("plot_humanize_model", "deepseek/deepseek-v3.2")
            temperature = get_setting("plot_humanize_temperature", 0.8)
            max_tokens = get_setting("plot_humanize_max_tokens", 2000)
        elif pipeline_type == 'daily':
            model = get_setting("daily_humanize_model", "deepseek/deepseek-v3.2")
            temperature = get_setting("daily_humanize_temperature", 0.8)
            max_tokens = get_setting("daily_humanize_max_tokens", 4000)
        elif pipeline_type == 'hub':
            model = get_setting("hub_humanize_model", "deepseek/deepseek-v3.2")
            temperature = get_setting("hub_humanize_temperature", 0.8)
            max_tokens = get_setting("hub_humanize_max_tokens", 4000)
        else:
            raise ValueError(f"Unknown pipeline type: {pipeline_type}")
        
        prompt = f"""You are a senior entertainment journalist with 15+ years of experience writing for publications like Variety, The Hindu, and Filmfare. Your writing is sharp, engaging, and reads like it was crafted by a human who genuinely loves cinema — not generated by AI.

DRAFT CONTENT:
{draft_content}

YOUR TASK:
Rewrite the draft into a polished, publish-ready article in HTML format. Write as if you're explaining this movie to an enthusiastic reader who wants the full picture — cast, story, release, buzz — in a compelling read.

WRITING STYLE:
- Conversational but authoritative — like a knowledgeable friend, not a press release
- Vary sentence length deliberately: short punchy sentences for impact, longer ones for context
- Lead each section with the most interesting detail, not the most obvious one
- Use specific, vivid language — avoid vague filler words
- Write in present/future tense for upcoming movies ("hits screens", "stars", "is set to release")
- Active voice throughout

STRICTLY AVOID:
- AI phrases: "It's worth noting", "Delve into", "Needless to say", "Interestingly", "Comprehensive", "Testament to", "Groundbreaking", "Game-changer", "In conclusion", "To summarize", "Captivating", "Remarkable", "In the world of"
- Repetitive sentence starters — never start two consecutive sentences with the same word
- Passive constructions: "is expected to be", "is said to be", "is believed to"
- Hollow hype: "highly anticipated", "blockbuster", "eagerly awaited" — show why it matters instead
- Restating the title or obvious facts as the opening line

HTML FORMAT RULES:
- Use only these tags: <h2>, <h3>, <p>, <strong>, <em>, <ul>, <li>, <ol>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <blockquote>, <br>
- Do NOT include <html>, <head>, <body>, <title>, or any wrapper tags
- Do NOT include inline styles or CSS classes
- Do NOT wrap output in markdown code blocks or backticks
- Start directly with the first HTML tag — no preamble
- Structure the article with clear <h2> sections (Cast & Crew, Story, Release Details, etc.)
- Use <table> for cast/crew lists, release dates, or any structured data
- Use <blockquote> for notable quotes from cast or crew if present in the draft
- Use <strong> to highlight key names, dates, and figures — not for decoration

CONTENT RULES:
- Preserve every fact, name, date, number, and detail from the draft — never invent or omit
- Do not add information not present in the draft
- Keep all cast/crew names exactly as written
- If the draft mentions box office numbers, budgets, or collections — keep them precise

Return only the HTML content. No explanations, no markdown, no wrapper tags."""
        
        result = call_openrouter(model, prompt, temperature, max_tokens)
        
        if not result:
            logger.warning("Humanization failed, using draft")
            return draft_content
        
        return result
        
    except Exception as e:
        logger.error(f"Humanization stage failed: {e}")
        return draft_content


def stage_seo(humanized_content: str, title: str, pipeline_type: str) -> Optional[Dict]:
    """
    Stage 3: SEO optimization
    pipeline_type: 'news', 'daily', 'hub' (NOT plot)
    """
    try:
        logger.info(f"STAGE 3: SEO Optimization ({pipeline_type})")
        
        if pipeline_type == 'news':
            model = get_setting("news_seo_model", "openai/gpt-4-turbo")
            temperature = get_setting("news_seo_temperature", 0.5)
            max_tokens = get_setting("news_seo_max_tokens", 4000)
        elif pipeline_type == 'daily':
            model = get_setting("daily_seo_model", "openai/gpt-4-turbo")
            temperature = get_setting("daily_seo_temperature", 0.5)
            max_tokens = get_setting("daily_seo_max_tokens", 2000)
        elif pipeline_type == 'hub':
            model = get_setting("hub_seo_model", "openai/gpt-4-turbo")
            temperature = get_setting("hub_seo_temperature", 0.5)
            max_tokens = get_setting("hub_seo_max_tokens", 2000)
        else:
            raise ValueError(f"SEO not supported for: {pipeline_type}")
        
        prompt = f"""You are an SEO specialist for an Indian entertainment news website.

TITLE: {title}
CONTENT SUMMARY:
{humanized_content[:1500]}

Generate SEO metadata. Return ONLY valid JSON, no explanation, no markdown fences.

{{
  "meta_title": "60 chars max. Include primary keyword naturally. No clickbait.",
  "meta_description": "155 chars max. One compelling sentence covering what, who, and why it matters. Include primary keyword.",
  "tags": ["8-12 tags", "mix of: movie title", "actor names", "genre", "language", "box office", "relevant keywords"]
}}"""
        
        result = call_openrouter(model, prompt, temperature, max_tokens)
        
        if result:
            return extract_json_from_text(result)
        
        return None
        
    except Exception as e:
        logger.error(f"SEO stage failed: {e}")
        return None


def stage_image_generation(title: str) -> Optional[str]:
    """Stage 4: Generate featured image (News only)"""
    try:
        logger.info("STAGE 4: Image Generation")
        
        model = get_setting("news_image_model", "black-forest-labs/flux-schnell")
        width = get_setting("news_image_width", 1024)
        height = get_setting("news_image_height", 768)
        
        prompt = f"""Digital art, cinematic featured image for an Indian entertainment article about '{title}'.
        
        VISUAL: Bold typography with '{title}' as hero text, dramatic cinematic lighting, deep rich color grading — golds, blues, or crimson. Abstract Bollywood or cinema motif in background — film reel, clapperboard, or spotlight silhouette.
        
        STYLE: Movie poster meets editorial. Dark background. High contrast. No real faces or people. No text other than '{title}'.
        
        OUTPUT: Sharp, 16:9 ratio."""
        
        image_url = call_openrouter_image(model, prompt, width, height)
        
        if not image_url:
            return None
        
        file_uuid = upload_file_to_directus(file_url=image_url, title=slugify(title))
        return file_uuid
        
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return None


def tavily_research(query: str) -> str:
    """Research using Tavily API, return compiled context"""
    try:
        logger.info(f"STAGE 0: Tavily Research - {query}")
        
        max_results = get_setting("tavily_max_results", 5)
        results = tavily_search(query, max_results)
        
        if not results:
            return ""
        
        context_parts = []
        for i, result in enumerate(results, 1):
            title = result.get('title', '')
            content = result.get('content', '')[:500]
            url = result.get('url', '')
            context_parts.append(f"Source {i}: {title}\n{content}...\nURL: {url}")
        
        return "\n\n".join(context_parts)
        
    except Exception as e:
        logger.error(f"Tavily research failed: {e}")
        return ""


def extract_people_from_text(text: str, existing_people_ids: List[str]) -> List[str]:
    """Extract people names from text and create if needed"""
    try:
        logger.info("Extracting people from article content")
        
        people_result = directus_get("/items/people?fields=id,name&limit=1000")
        existing_people = people_result.get('data', [])
        existing_names = [p['name'] for p in existing_people]
        
        model = get_setting("budget_model", "openai/gpt-4o-mini")
        
        prompt = f"""Extract all people from this text — actors, directors, producers, writers, composers, cinematographers, distributors.
        
        TEXT:
        {text[:1000]}

        ALREADY KNOWN (skip these):
        {', '.join(existing_names[:100])}

        Return ONLY a JSON array of NEW names not in the known list. If none, return [].
        ["Name 1", "Name 2"]"""
        
        result = call_openrouter(model, prompt, 0.3, 500)
        
        if not result:
            return existing_people_ids
        
        new_names = extract_json_from_text(result)
        
        if not new_names or not isinstance(new_names, list):
            return existing_people_ids
        
        logger.info(f"Found {len(new_names)} new people")
        
        all_people_ids = list(existing_people_ids)
        
        for name in new_names:
            if not name or not isinstance(name, str):
                continue
            
            person_id = get_or_create_person(name, ['actor'])
            if person_id and person_id not in all_people_ids:
                all_people_ids.append(person_id)
        
        return all_people_ids
        
    except Exception as e:
        logger.error(f"People extraction failed: {e}")
        return existing_people_ids

# ============================================================================
# INTERLINKING
# ============================================================================

def add_internal_links(content: str, context: Dict) -> str:
    """
    Add internal links to content
    context = {
        'movie_ids': [...],
        'people_ids': [...],
        'day_number': 5,
        'current_slug': '...'
    }
    """
    try:
        logger.info("Adding internal links")
        
        movie_ids = context.get('movie_ids', [])
        people_ids = context.get('people_ids', [])
        day_number = context.get('day_number')
        current_slug = context.get('current_slug', '')
        
        # Fetch movie and people data
        movies = []
        for mid in movie_ids:
            result = directus_get(f"/items/movies/{mid}?fields=title,slug")
            movie = result.get('data', {})
            if movie:
                movies.append(movie)
        
        people = []
        for pid in people_ids:
            result = directus_get(f"/items/people/{pid}?fields=name,slug")
            person = result.get('data', {})
            if person:
                people.append(person)
        
        # Link movies (first 2 occurrences only)
        for movie in movies:
            title = movie.get('title', '')
            slug = movie.get('slug', '')
            
            if not title or not slug:
                continue
            
            pattern = re.compile(re.escape(title), re.IGNORECASE)
            count = 0

            def replace_movie(match, slug=slug):
                nonlocal count
                count += 1
                if count <= 2:
                    return f'<a href="/box-office/{slug}">{match.group()}</a>'
                return match.group()

            content = pattern.sub(replace_movie, content)
        
        # Link people (first 2 occurrences only)
        for person in people:
            name = person.get('name', '')
            slug = person.get('slug', '')
            
            if not name or not slug:
                continue
            
            pattern = re.compile(re.escape(name), re.IGNORECASE)
            count = 0

            def replace_person(match, slug=slug):
                nonlocal count
                count += 1
                if count <= 2:
                    return f'<a href="/people/{slug}">{match.group()}</a>'
                return match.group()

            content = pattern.sub(replace_person, content)
        
        # Link "Day X" mentions (first 3 occurrences only)
        if day_number and movies:
            movie_slug = movies[0].get('slug', '')
            if movie_slug:
                pattern = re.compile(r'\bDay (\d+)\b')
                count = 0

                def replace_day(match, movie_slug=movie_slug):
                    nonlocal count
                    count += 1
                    if count <= 3:
                        day_num = match.group(1)
                        return f'<a href="/box-office/{movie_slug}/day-{day_num}">Day {day_num}</a>'
                    return match.group()

                content = pattern.sub(replace_day, content)
        
        # Add related articles section
        related_html = get_related_articles_html(movie_ids, people_ids, current_slug)
        if related_html:
            content = content + "\n\n" + related_html
        
        logger.info("Internal links added")
        return content
        
    except Exception as e:
        logger.error(f"Interlinking failed: {e}")
        return content


def get_related_articles_html(movie_ids: List[str], people_ids: List[str], current_slug: str, limit: int = 3) -> str:
    """Get related articles HTML section"""
    try:
        if not movie_ids and not people_ids:
            return ""

        # Build proper Directus _or filter params
        params = []
        for i, mid in enumerate(movie_ids):
            params.append(f"filter[_or][{i}][movie_id][_contains]={mid}")
        offset = len(movie_ids)
        for i, pid in enumerate(people_ids):
            params.append(f"filter[_or][{offset + i}][people_id][_contains]={pid}")

        params.append(f"filter[slug][_neq]={current_slug}")
        params.append("filter[status][_eq]=published")
        params.append("sort=-date_created")
        params.append(f"limit={limit}")
        params.append("fields=title,slug")

        query_string = "&".join(params)
        result = directus_get(f"/items/news_articles?{query_string}")
        articles = result.get('data', [])

        if not articles:
            return ""

        html = '<h2>Related Articles</h2>\n<ul>\n'
        for article in articles:
            title = article.get('title', '')
            slug = article.get('slug', '')
            if title and slug:
                html += f'  <li><a href="/news/{slug}">{title}</a></li>\n'
        html += '</ul>'

        return html

    except Exception as e:
        logger.error(f"Related articles failed: {e}")
        return ""