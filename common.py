"""
common.py - Shared utilities for Box Office automation system
Handles: Directus, OpenRouter, Tavily, Slack, Redis, File operations
"""

import os
import json
import time
import requests
import redis
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from fuzzywuzzy import fuzz
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# REDIS CONNECTION & SETTINGS
# ============================================================================

def get_redis_connection():
    """Get Redis connection"""
    from config import REDIS_HOST, REDIS_PORT, REDIS_DB
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True
    )


def get_setting(key: str, default: Any = None) -> Any:
    """Get setting from Redis"""
    try:
        r = get_redis_connection()
        value = r.get(key)
        if value is None:
            return default
        try:
            return json.loads(value)
        except:
            return value
    except Exception as e:
        logger.error(f"Error getting setting {key}: {e}")
        return default


def set_setting(key: str, value: Any) -> bool:
    """Set setting in Redis"""
    try:
        r = get_redis_connection()
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        r.set(key, value)
        return True
    except Exception as e:
        logger.error(f"Error setting {key}: {e}")
        return False


# ============================================================================
# HTTP REQUEST WRAPPER WITH RETRY
# ============================================================================

def request_with_retry(
    method: str,
    url: str,
    headers: Dict = None,
    json_body: Dict = None,
    data: Any = None,
    files: Dict = None,
    max_retries: int = 3,
    timeout: int = 30
) -> requests.Response:
    """Make HTTP request with retry logic"""
    
    for attempt in range(max_retries):
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method.upper() == "POST":
                response = requests.post(
                    url, headers=headers, json=json_body, 
                    data=data, files=files, timeout=timeout
                )
            elif method.upper() == "PATCH":
                response = requests.patch(
                    url, headers=headers, json=json_body, timeout=timeout
                )
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers, timeout=timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Request failed after {max_retries} attempts: {e}")
                raise
            logger.warning(f"Request attempt {attempt + 1} failed, retrying: {e}")
            time.sleep(2 ** attempt)  # Exponential backoff


# ============================================================================
# DIRECTUS API
# ============================================================================

def directus_url():
    """Get Directus URL from settings"""
    return get_setting("directus_url", "https://admin.gadgeek.in")


def directus_token():
    """Get Directus token from settings"""
    return get_setting("directus_token")


def directus_headers():
    """Get Directus headers"""
    return {
        "Content-Type": "application/json"
        # No token needed - Public Access enabled
    }


def directus_get(endpoint: str, params: Dict = None) -> Dict:
    """GET request to Directus"""
    url = f"{directus_url()}{endpoint}"
    headers = directus_headers()
    
    try:
        response = request_with_retry("GET", url, headers=headers)
        return response.json()
    except Exception as e:
        logger.error(f"Directus GET {endpoint} failed: {e}")
        raise


def directus_post(endpoint: str, data: Dict) -> Dict:
    """POST request to Directus"""
    url = f"{directus_url()}{endpoint}"
    headers = directus_headers()
    
    try:
        response = request_with_retry("POST", url, headers=headers, json_body=data)
        return response.json()
    except Exception as e:
        logger.error(f"Directus POST {endpoint} failed: {e}")
        logger.error(f"Data: {json.dumps(data, indent=2)}")
        raise


def directus_patch(endpoint: str, data: Dict) -> Dict:
    """PATCH request to Directus"""
    url = f"{directus_url()}{endpoint}"
    headers = directus_headers()
    
    try:
        response = request_with_retry("PATCH", url, headers=headers, json_body=data)
        return response.json()
    except Exception as e:
        logger.error(f"Directus PATCH {endpoint} failed: {e}")
        raise


def directus_delete(endpoint: str) -> bool:
    """DELETE request to Directus"""
    url = f"{directus_url()}{endpoint}"
    headers = directus_headers()
    
    try:
        request_with_retry("DELETE", url, headers=headers)
        return True
    except Exception as e:
        logger.error(f"Directus DELETE {endpoint} failed: {e}")
        return False


def upload_file_to_directus(file_path: str = None, file_url: str = None, title: str = None) -> Optional[str]:
    """
    Upload file to Directus Files
    Returns: file UUID or None
    """
    try:
        # Download from URL if provided
        if file_url:
            logger.info(f"Downloading file from {file_url}")
            response = requests.get(file_url, timeout=30)
            response.raise_for_status()
            file_content = response.content
            filename = title or file_url.split('/')[-1]
        
        # Or read from local path
        elif file_path:
            with open(file_path, 'rb') as f:
                file_content = f.read()
            filename = title or os.path.basename(file_path)
        
        else:
            raise ValueError("Either file_path or file_url must be provided")
        
        # Upload to Directus
        url = f"{directus_url()}/files"
        files = {'file': (filename, file_content)}
        
        response = request_with_retry("POST", url, files=files)
        result = response.json()
        
        file_id = result.get('data', {}).get('id')
        logger.info(f"File uploaded successfully: {file_id}")
        return file_id
        
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        return None


# ============================================================================
# OPENROUTER API
# ============================================================================

def openrouter_api_key():
    """Get OpenRouter API key"""
    return get_setting("openrouter_api_key")


def call_openrouter(
    model: str,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    system_prompt: str = None
) -> Optional[str]:
    """
    Call OpenRouter API for text generation
    Returns: generated text or None
    """
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {openrouter_api_key()}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        response = request_with_retry("POST", url, headers=headers, json_body=payload)
        result = response.json()
        
        content = result['choices'][0]['message']['content']
        logger.info(f"OpenRouter call successful ({model})")
        return content
        
    except Exception as e:
        logger.error(f"OpenRouter API call failed: {e}")
        return None


def call_openrouter_image(
    model: str,
    prompt: str,
    width: int = 1024,
    height: int = 768
) -> Optional[str]:
    """
    Call OpenRouter for image generation
    Returns: image URL or None
    """
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {openrouter_api_key()}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "image_size": f"{width}x{height}"
        }
        
        response = request_with_retry("POST", url, headers=headers, json_body=payload)
        result = response.json()
        
        # Extract image URL from response
        image_url = result['choices'][0]['message']['content']
        logger.info(f"Image generated successfully ({model})")
        return image_url
        
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return None


# ============================================================================
# TAVILY SEARCH API
# ============================================================================

def tavily_api_key():
    """Get Tavily API key"""
    return get_setting("tavily_api_key")


def tavily_search(query: str, max_results: int = 5) -> List[Dict]:
    """
    Search using Tavily API
    Returns: list of search results
    """
    try:
        url = "https://api.tavily.com/search"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "api_key": tavily_api_key(),
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "include_raw_content": False
        }
        
        response = request_with_retry("POST", url, headers=headers, json_body=payload)
        result = response.json()
        
        results = result.get('results', [])
        logger.info(f"Tavily search returned {len(results)} results")
        return results
        
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return []


# ============================================================================
# SLACK API
# ============================================================================

def slack_token():
    """Get Slack bot token"""
    return get_setting("slack_bot_token")


def slack_channel():
    """Get Slack channel ID"""
    return get_setting("slack_channel_id")


def slack_post_message(blocks: List[Dict], text: str = "New notification") -> Dict:
    """
    Post message to Slack
    Returns: {channel, ts} or None
    """
    try:
        url = "https://slack.com/api/chat.postMessage"
        
        headers = {
            "Authorization": f"Bearer {slack_token()}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "channel": slack_channel(),
            "blocks": blocks,
            "text": text
        }
        
        response = request_with_retry("POST", url, headers=headers, json_body=payload)
        result = response.json()
        
        if result.get("ok"):
            return {
                "channel": result.get("channel"),
                "ts": result.get("ts")
            }
        else:
            logger.error(f"Slack post failed: {result.get('error')}")
            return None
            
    except Exception as e:
        logger.error(f"Slack post message failed: {e}")
        return None


def slack_delete_message(channel: str, ts: str) -> bool:
    """Delete Slack message"""
    try:
        url = "https://slack.com/api/chat.delete"
        
        headers = {
            "Authorization": f"Bearer {slack_token()}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "channel": channel,
            "ts": ts
        }
        
        response = request_with_retry("POST", url, headers=headers, json_body=payload)
        result = response.json()
        
        return result.get("ok", False)
        
    except Exception as e:
        logger.error(f"Slack delete message failed: {e}")
        return False


def slack_ephemeral(response_url: str, text: str) -> bool:
    """Send ephemeral message (only visible to user)"""
    try:
        payload = {
            "text": text,
            "response_type": "ephemeral",
            "replace_original": False
        }
        
        response = request_with_retry("POST", response_url, json_body=payload)
        return True
        
    except Exception as e:
        logger.error(f"Slack ephemeral failed: {e}")
        return False


# ============================================================================
# REDIS QUEUE OPERATIONS
# ============================================================================

def enqueue_job(queue_name: str, job_data: Dict) -> bool:
    """Add job to Redis queue"""
    try:
        r = get_redis_connection()
        r.rpush(queue_name, json.dumps(job_data))
        logger.info(f"Job enqueued to {queue_name}: {job_data.get('type')}")
        return True
    except Exception as e:
        logger.error(f"Enqueue failed: {e}")
        return False


def dequeue_job(queue_name: str, timeout: int = 0) -> Optional[Dict]:
    """Get job from Redis queue (blocking)"""
    try:
        r = get_redis_connection()
        result = r.blpop(queue_name, timeout=timeout)
        if result:
            _, job_json = result
            return json.loads(job_json)
        return None
    except Exception as e:
        logger.error(f"Dequeue failed: {e}")
        return None


def store_failed_job(job_data: Dict) -> bool:
    """Store failed job for retry"""
    try:
        r = get_redis_connection()
        job_id = f"failed_job:{datetime.now().timestamp()}"
        r.set(job_id, json.dumps(job_data), ex=86400)  # 24 hour expiry
        logger.info(f"Failed job stored: {job_id}")
        return True
    except Exception as e:
        logger.error(f"Store failed job error: {e}")
        return False


def get_failed_jobs() -> List[Dict]:
    """Get all failed jobs for retry"""
    try:
        r = get_redis_connection()
        keys = r.keys("failed_job:*")
        jobs = []
        for key in keys:
            job_json = r.get(key)
            if job_json:
                jobs.append(json.loads(job_json))
                r.delete(key)  # Remove after retrieving
        return jobs
    except Exception as e:
        logger.error(f"Get failed jobs error: {e}")
        return []


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def slugify(text: str) -> str:
    """Convert text to URL-friendly slug"""
    import re
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def fuzzy_match(text1: str, text2: str, threshold: int = 90) -> bool:
    """Check if two texts are similar (fuzzy match)"""
    ratio = fuzz.ratio(text1.lower(), text2.lower())
    return ratio >= threshold


def calculate_day_number(release_date: str, target_date: str = None) -> int:
    """
    Calculate day number from release date
    target_date defaults to today
    """
    from datetime import datetime
    
    release = datetime.strptime(release_date, "%Y-%m-%d")
    target = datetime.strptime(target_date, "%Y-%m-%d") if target_date else datetime.now()
    
    delta = (target - release).days + 1
    return delta


def parse_number_from_text(text: str) -> Optional[float]:
    """
    Parse number from text like "50.5 Cr" or "5.5 L"
    Returns value in crores
    """
    import re
    
    if not text:
        return None
    
    # Remove commas
    text = text.replace(',', '')
    
    # Extract number
    match = re.search(r'([\d.]+)', text)
    if not match:
        return None
    
    number = float(match.group(1))
    
    # Convert to crores
    if 'L' in text.upper() or 'LAC' in text.upper() or 'LAKH' in text.upper():
        number = number / 100  # Lakh to Crore
    elif 'K' in text.upper() or 'THOUSAND' in text.upper():
        number = number / 10000  # Thousand to Crore
    # Assume Cr if no unit
    
    return number


def extract_json_from_text(text: str) -> Optional[Dict]:
    """Extract JSON object from text (handles markdown code blocks)"""
    import re
    
    # Remove markdown code blocks
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    try:
        return json.loads(text.strip())
    except:
        # Try to find JSON object in text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass
        return None


# ============================================================================
# LOGGING HELPER
# ============================================================================

def log_job_start(job_type: str, job_data: Dict):
    """Log job start"""
    logger.info(f"=" * 60)
    logger.info(f"JOB START: {job_type}")
    logger.info(f"Data: {json.dumps(job_data, indent=2)}")
    logger.info(f"=" * 60)


def log_job_complete(job_type: str):
    """Log job completion"""
    logger.info(f"JOB COMPLETE: {job_type}")
    logger.info(f"=" * 60)


def log_job_failed(job_type: str, error: str):
    """Log job failure"""
    logger.error(f"JOB FAILED: {job_type}")
    logger.error(f"Error: {error}")
    logger.error(f"=" * 60)