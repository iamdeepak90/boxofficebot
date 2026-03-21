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
from bs4 import BeautifulSoup
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
        socket_timeout=10,
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
    """HTTP request with exponential backoff retry"""
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            wait_time = 2 ** attempt
            logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
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

def upload_file_to_directus(file_path: str = None, file_url: str = None, title: str = None) -> Optional[str]:
    """Upload file to Directus and return UUID"""
    try:
        base_url = get_setting('directus_url', 'https://admin.boxofficetalk.com')
        token = get_setting('directus_token', '')
        
        headers = {}
        if token:
            headers['Authorization'] = f"Bearer {token}"
        
        if file_url:
            # Download file first
            response = requests.get(file_url, timeout=30)
            response.raise_for_status()
            file_data = response.content
            filename = title or file_url.split('/')[-1]
        elif file_path:
            with open(file_path, 'rb') as f:
                file_data = f.read()
            filename = title or os.path.basename(file_path)
        else:
            return None
        
        files = {'file': (filename, file_data)}
        response = requests.post(f"{base_url}/files", headers=headers, files=files, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        file_uuid = result.get('data', {}).get('id')
        logger.info(f"File uploaded: {file_uuid}")
        return file_uuid
        
    except Exception as e:
        logger.error(f"File upload error: {e}")
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
                page.goto(url, wait_until='networkidle', timeout=30000)
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
    """Parse Sacnilk box office table"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        table = soup.find('table')
        
        if not table:
            return None
        
        rows = table.find_all('tr')
        if len(rows) < 2:
            return None
        
        # Parse header
        header = rows[0]
        headers = [th.text.strip().lower() for th in header.find_all(['th', 'td'])]
        
        # Find column indices
        day_idx = next((i for i, h in enumerate(headers) if 'day' in h), 0)
        india_net_idx = next((i for i, h in enumerate(headers) if 'india net' in h or 'nett' in h), None)
        india_gross_idx = next((i for i, h in enumerate(headers) if 'india gross' in h or 'gross india' in h), None)
        overseas_idx = next((i for i, h in enumerate(headers) if 'overseas' in h or 'international' in h), None)
        
        # Parse data rows
        days_data = []
        
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            
            first_cell = cells[0].text.strip().lower()
            if 'total' in first_cell:
                continue
            
            day_text = cells[day_idx].text.strip()
            day_match = re.search(r'(\d+)', day_text)
            
            if not day_match:
                continue
            
            day_number = int(day_match.group(1))
            
            india_net = 0
            if india_net_idx is not None and india_net_idx < len(cells):
                india_net = parse_number_from_text(cells[india_net_idx].text.strip()) or 0
            
            days_data.append({
                'day_number': day_number,
                'india_net': india_net
            })
        
        # Parse totals
        totals = {}
        for row in reversed(rows):
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            
            first_cell = cells[0].text.strip().lower()
            if 'total' in first_cell:
                if india_gross_idx and india_gross_idx < len(cells):
                    totals['india_gross_total'] = parse_number_from_text(cells[india_gross_idx].text.strip()) or 0
                
                if overseas_idx and overseas_idx < len(cells):
                    totals['overseas_total'] = parse_number_from_text(cells[overseas_idx].text.strip()) or 0
                
                break
        
        return {'days': days_data, 'totals': totals}
        
    except Exception as e:
        logger.error(f"Table parsing failed: {e}")
        return None

def scrape_sacnilk_upcoming() -> List[Dict]:
    """Scrape Sacnilk upcoming movies page"""
    try:
        url = "https://sacnilk.com/entertainmenttopbar/Upcoming_Movies"
        html = get_page_content(url)
        
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
            date_tag = card.find("div", class_="text-[10px] text-gray-300 font-medium")
            img_tag = card.find("img")

            title = title_tag.get_text(strip=True) if title_tag else None
            release_date_raw = date_tag.get_text(strip=True) if date_tag else None
            poster_url = img_tag.get("src") if img_tag else None

            genres = card.get("data-genres", "").strip()
            languages = card.get("data-languages", "").strip()

            release_date = None
            if release_date_raw:
                try:
                    release_date = datetime.strptime(release_date_raw, "%b %d, %Y").date().isoformat()
                except ValueError:
                    release_date = release_date_raw

            movies.append({
                "title": title,
                "movie_url": urljoin("https://sacnilk.com", href),
                "slug": href.strip("/").split("/")[-1],
                "poster_url": poster_url,
                "image_alt": title,
                "release_date": release_date,
                "release_date_raw": release_date_raw,
                "languages": [x.strip() for x in languages.split(",")] if languages else [],
                "genres": [x.strip() for x in genres.split(",")] if genres else [],
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
        
        # TODO: Adjust selectors based on actual HTML
        details = {}
        
        return details
        
    except Exception as e:
        logger.error(f"Movie details scrape failed: {e}")
        return None

# ============================================================================
# MOVIE & PEOPLE HELPERS
# ============================================================================

def get_or_create_person(name: str, person_type: str = 'actor') -> Optional[str]:
    """Get or create person, return UUID"""
    try:
        # Check if exists
        result = directus_get(f"/items/people?filter[name][_eq]={name}&limit=1")
        existing = result.get('data', [])
        
        if existing and len(existing) > 0:
            return existing[0]['id']
        
        # Create new
        person_data = {
            'name': name,
            'slug': slugify(name),
            'type': [person_type],
            'status': 'published'
        }
        
        result = directus_post('/items/people', person_data)
        person_id = result.get('data', {}).get('id')
        
        if person_id:
            logger.info(f"Created person: {name} ({person_id})")
        
        return person_id
        
    except Exception as e:
        logger.error(f"Get/create person failed: {e}")
        return None

def check_duplicate_movie(title: str, sacnilk_url: str) -> Optional[Dict]:
    """Check if movie already exists"""
    try:
        # Exact URL match
        result = directus_get(f"/items/movies?filter[sacnilk_source_url][_eq]={sacnilk_url}&limit=1")
        exact_match = result.get('data', [])
        
        if exact_match and len(exact_match) > 0:
            return exact_match[0]
        
        # Fuzzy title match
        threshold = get_setting('fuzzy_match_threshold', 90)
        result = directus_get("/items/movies?limit=1000&fields=id,title,sacnilk_source_url")
        all_movies = result.get('data', [])
        
        for movie in all_movies:
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
            model = get_setting("news_generation_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("news_generation_temperature", 0.7)
            max_tokens = get_setting("news_generation_max_tokens", 8000)
        elif pipeline_type == 'plot':
            model = get_setting("plot_generation_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("plot_generation_temperature", 0.7)
            max_tokens = get_setting("plot_generation_max_tokens", 2000)
        elif pipeline_type == 'daily':
            model = get_setting("daily_generation_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("daily_generation_temperature", 0.7)
            max_tokens = get_setting("daily_generation_max_tokens", 4000)
        elif pipeline_type == 'hub':
            model = get_setting("hub_generation_model", "anthropic/claude-3.5-sonnet")
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
            model = get_setting("news_humanize_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("news_humanize_temperature", 0.8)
            max_tokens = get_setting("news_humanize_max_tokens", 8000)
        elif pipeline_type == 'plot':
            model = get_setting("plot_humanize_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("plot_humanize_temperature", 0.8)
            max_tokens = get_setting("plot_humanize_max_tokens", 2000)
        elif pipeline_type == 'daily':
            model = get_setting("daily_humanize_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("daily_humanize_temperature", 0.8)
            max_tokens = get_setting("daily_humanize_max_tokens", 4000)
        elif pipeline_type == 'hub':
            model = get_setting("hub_humanize_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("hub_humanize_temperature", 0.8)
            max_tokens = get_setting("hub_humanize_max_tokens", 4000)
        else:
            raise ValueError(f"Unknown pipeline type: {pipeline_type}")
        
        prompt = f"""Rewrite this content to sound more natural and human.

CONTENT:
{draft_content}

REQUIREMENTS:
- Remove AI-like phrases: "It's worth noting", "Interestingly", "Needless to say", "Delve into"
- Use varied sentence structures
- Add conversational flow
- Keep all facts and data intact
- Use active voice
- Professional journalistic tone

Return only the rewritten content."""
        
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
        
        prompt = f"""Optimize this content for SEO.

TITLE: {title}

CONTENT:
{humanized_content}

OPTIMIZE:
1. Add proper H1, H2, H3 headings
2. Create meta title (60 chars max)
3. Create meta description (155 chars max)
4. Ensure keyword density
5. Add FAQ section
6. Optimize for featured snippets

Return ONLY JSON:
{{
  "content": "<h1>...</h1><p>...</p>...",
  "meta_title": "...",
  "meta_description": "..."
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
        
        prompt = f"Professional featured image for article: {title}. Cinematic, high quality, movie poster style."
        
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
        
        prompt = f"""Extract all people names (actors, directors, producers) from this text.

TEXT:
{text[:1000]}

ALREADY KNOWN:
{', '.join(existing_names[:100])}

Return ONLY JSON array of NEW names:
["Name 1", "Name 2"]

If no new people, return: []"""
        
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
            
            person_id = get_or_create_person(name, 'actor')
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
            
            # Find first 2 occurrences
            pattern = re.compile(re.escape(title), re.IGNORECASE)
            matches = list(pattern.finditer(content))
            
            for i, match in enumerate(matches[:2]):
                if i == 0:
                    # First occurrence - link to hub
                    link = f'<a href="/box-office/{slug}">{match.group()}</a>'
                    content = content[:match.start()] + link + content[match.end():]
        
        # Link people (first 2 occurrences only)
        for person in people:
            name = person.get('name', '')
            slug = person.get('slug', '')
            
            if not name or not slug:
                continue
            
            pattern = re.compile(re.escape(name), re.IGNORECASE)
            matches = list(pattern.finditer(content))
            
            for i, match in enumerate(matches[:2]):
                link = f'<a href="/people/{slug}">{match.group()}</a>'
                content = content[:match.start()] + link + content[match.end():]
        
        # Link "Day X" mentions (if day_number provided)
        if day_number and movies:
            movie_slug = movies[0].get('slug', '')
            if movie_slug:
                pattern = re.compile(r'\bDay (\d+)\b')
                matches = list(pattern.finditer(content))
                
                for match in matches[:3]:
                    day_num = match.group(1)
                    link = f'<a href="/box-office/{movie_slug}/day-{day_num}">Day {day_num}</a>'
                    content = content[:match.start()] + link + content[match.end():]
        
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
        # Build filter query
        filters = []
        
        if movie_ids:
            movie_filter = " OR ".join([f"movie_id[_contains]={mid}" for mid in movie_ids])
            filters.append(f"({movie_filter})")
        
        if people_ids:
            people_filter = " OR ".join([f"people_id[_contains]={pid}" for pid in people_ids])
            filters.append(f"({people_filter})")
        
        if not filters:
            return ""
        
        # Query Directus
        filter_str = " OR ".join(filters)
        result = directus_get(
            f"/items/news_articles?filter[_or][0][{filter_str}]&filter[slug][_neq]={current_slug}&filter[status][_eq]=published&sort=-date_created&limit={limit}&fields=title,slug"
        )
        
        articles = result.get('data', [])
        
        if not articles:
            return ""
        
        # Build HTML
        html = '<h2>Related Articles</h2>\n<ul>\n'
        for article in articles:
            title = article.get('title', '')
            slug = article.get('slug', '')
            html += f'  <li><a href="/news/{slug}">{title}</a></li>\n'
        html += '</ul>'
        
        return html
        
    except Exception as e:
        logger.error(f"Related articles failed: {e}")
        return ""