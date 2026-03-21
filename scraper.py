"""
scraper.py - Live box office scraper with backfill
Runs: Every 4 hours
Scrapes: Main movie page (not day-wise pages)
"""

import sys
import os
from common import *
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import time
import random
import schedule
import time as time_module


# ============================================================================
# PLAYWRIGHT SETUP (STEALTH MODE)
# ============================================================================

try:
    from playwright.sync_api import sync_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not available, using requests fallback")


def get_page_content_playwright(url: str) -> Optional[str]:
    """
    Fetch page content using Playwright with stealth mode
    Returns: HTML content or None
    """
    try:
        with sync_playwright() as p:
            # Get proxy if configured
            proxies = get_setting("scraper_proxies", [])
            proxy_config = None
            
            if proxies:
                proxy = random.choice(proxies)
                proxy_config = {"server": proxy}
                logger.info(f"Using proxy: {proxy}")
            
            # Launch browser
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox'
                ],
                proxy=proxy_config
            )
            
            # Create context with random user agent
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            
            page = context.new_page()
            
            # Navigate
            page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait a bit for JS to load
            page.wait_for_timeout(2000)
            
            # Get content
            content = page.content()
            
            browser.close()
            
            return content
            
    except Exception as e:
        logger.error(f"Playwright fetch failed: {e}")
        return None


def get_page_content(url: str) -> Optional[str]:
    """
    Fetch page content (Playwright preferred, requests fallback)
    Returns: HTML content or None
    """
    if PLAYWRIGHT_AVAILABLE:
        content = get_page_content_playwright(url)
        if content:
            return content
    
    # Fallback to requests
    try:
        logger.info("Using requests fallback")
        response = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"Requests fetch failed: {e}")
        return None


# ============================================================================
# SACNILK TABLE PARSING
# ============================================================================

def parse_box_office_table(html_content: str) -> Optional[Dict]:
    """
    Parse Sacnilk box office table
    Returns: {days: [...], totals: {...}}
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find box office table
        # NOTE: Adjust selectors based on actual Sacnilk HTML structure
        table = soup.find('table', class_='box-office-table')  # Placeholder
        
        if not table:
            # Try other common selectors
            table = soup.find('table')
        
        if not table:
            logger.error("Could not find box office table")
            return None
        
        rows = table.find_all('tr')
        
        if len(rows) < 2:
            logger.error("Table has insufficient rows")
            return None
        
        # Parse header to find column indices
        header = rows[0]
        headers = [th.text.strip().lower() for th in header.find_all(['th', 'td'])]
        
        # Find column indices
        day_idx = None
        india_net_idx = None
        india_gross_idx = None
        overseas_idx = None
        
        for i, h in enumerate(headers):
            if 'day' in h:
                day_idx = i
            elif 'india net' in h or 'nett india' in h:
                india_net_idx = i
            elif 'india gross' in h or 'gross india' in h:
                india_gross_idx = i
            elif 'overseas' in h or 'international' in h:
                overseas_idx = i
        
        logger.info(f"Column indices: day={day_idx}, india_net={india_net_idx}, india_gross={india_gross_idx}, overseas={overseas_idx}")
        
        # Parse data rows
        days_data = []
        
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            
            if len(cells) < 2:
                continue
            
            # Check if this is the total/footer row
            first_cell = cells[0].text.strip().lower()
            if 'total' in first_cell or 'gross' in first_cell:
                # This is the totals row, parse separately
                continue
            
            # Extract day number
            day_text = cells[day_idx].text.strip() if day_idx is not None else cells[0].text.strip()
            
            # Parse day number (could be "Day 1", "1", "D1", etc.)
            day_match = re.search(r'(\d+)', day_text)
            if not day_match:
                continue
            
            day_number = int(day_match.group(1))
            
            # Extract India Net
            india_net = 0
            if india_net_idx is not None and india_net_idx < len(cells):
                india_net_text = cells[india_net_idx].text.strip()
                india_net = parse_number_from_text(india_net_text) or 0
            
            days_data.append({
                'day_number': day_number,
                'india_net': india_net
            })
        
        # Parse totals from footer
        totals = {}
        
        # Find footer row (last row or row with "Total")
        for row in reversed(rows):
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            
            first_cell = cells[0].text.strip().lower()
            if 'total' in first_cell:
                # Extract totals
                if india_gross_idx is not None and india_gross_idx < len(cells):
                    india_gross_text = cells[india_gross_idx].text.strip()
                    totals['india_gross_total'] = parse_number_from_text(india_gross_text) or 0
                
                if overseas_idx is not None and overseas_idx < len(cells):
                    overseas_text = cells[overseas_idx].text.strip()
                    totals['overseas_total'] = parse_number_from_text(overseas_text) or 0
                
                break
        
        logger.info(f"Parsed {len(days_data)} days, totals: {totals}")
        
        return {
            'days': days_data,
            'totals': totals
        }
        
    except Exception as e:
        logger.error(f"Table parsing failed: {e}")
        return None


# ============================================================================
# SCRAPE SINGLE MOVIE
# ============================================================================

def scrape_movie(movie: Dict) -> Optional[Dict]:
    """
    Scrape box office data for single movie
    Returns: Parsed data or None
    """
    try:
        movie_id = movie['id']
        title = movie.get('title')
        sacnilk_url = movie.get('sacnilk_source_url')
        
        if not sacnilk_url:
            logger.warning(f"No Sacnilk URL for {title}")
            return None
        
        logger.info(f"Scraping: {title}")
        logger.info(f"URL: {sacnilk_url}")
        
        # Fetch page content
        html_content = get_page_content(sacnilk_url)
        
        if not html_content:
            logger.error(f"Failed to fetch content for {title}")
            return None
        
        # Parse table
        parsed_data = parse_box_office_table(html_content)
        
        if not parsed_data:
            logger.error(f"Failed to parse table for {title}")
            return None
        
        return parsed_data
        
    except Exception as e:
        logger.error(f"Scraping failed for {title}: {e}")
        return None


# ============================================================================
# UPDATE DAILY STATS
# ============================================================================

def update_daily_stats(movie_id: str, movie_title: str, release_date: str, days_data: List[Dict]):
    """
    Update/insert daily_stats entries
    Handle backfill with batching
    """
    try:
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        
        # Get existing daily_stats
        existing_result = directus_get(
            f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&fields=id,day_number,india_net&limit=1000"
        )
        existing_stats = existing_result.get('data', [])
        existing_days = {stat['day_number']: stat for stat in existing_stats}
        
        backfill_jobs = []
        updated_count = 0
        
        for day_data in days_data:
            day_number = day_data['day_number']
            india_net = day_data['india_net']
            
            # Calculate date for this day
            release = datetime.strptime(release_date, "%Y-%m-%d")
            day_date = release + timedelta(days=day_number - 1)
            day_date_str = day_date.strftime("%Y-%m-%d")
            
            is_today = (day_date_str == today_str)
            
            if day_number in existing_days:
                # Update existing
                existing_stat = existing_days[day_number]
                
                if is_today:
                    # Update today's data (live)
                    directus_patch(f"/items/daily_stats/{existing_stat['id']}", {
                        'india_net': india_net,
                        'is_estimate': True
                    })
                    updated_count += 1
                    logger.info(f"Updated Day {day_number} (today): ₹{india_net} Cr")
                    
                    # If has SEO content with prediction, queue regeneration
                    if existing_stat.get('seo_content'):
                        backfill_jobs.append({
                            'type': 'daily_box_office_actual',
                            'movie_id': movie_id,
                            'day_number': day_number,
                            'movie_title': movie_title,
                            'mode': 'actual',
                            'india_net': india_net
                        })
                
                # Else: don't update past days (already final)
                
            else:
                # Backfill: Create new entry
                logger.info(f"Backfilling Day {day_number}: ₹{india_net} Cr")
                
                stats_payload = {
                    'movie_id': movie_id,
                    'day_number': day_number,
                    'date': day_date_str,
                    'india_net': india_net,
                    'is_estimate': False,  # Past day (actual data)
                    'seo_content': '',  # Empty
                    'slug': slugify(f"{movie_title}-day-{day_number}-box-office-collection"),
                    'tags': [movie_title, f"day {day_number}", "box office collection"]
                }
                
                result = directus_post('/items/daily_stats', stats_payload)
                
                if result.get('data'):
                    # Queue AI job for backfilled day
                    backfill_jobs.append({
                        'type': 'daily_box_office_actual',
                        'movie_id': movie_id,
                        'day_number': day_number,
                        'movie_title': movie_title,
                        'mode': 'actual',
                        'india_net': india_net
                    })
                    updated_count += 1
        
        logger.info(f"Updated {updated_count} days")
        
        # Batch process backfill jobs
        if backfill_jobs:
            batch_size = get_setting("backfill_batch_size", 5)
            delay_seconds = get_setting("backfill_delay_seconds", 120)
            
            logger.info(f"Backfill: {len(backfill_jobs)} jobs (batch size: {batch_size})")
            
            for i, job in enumerate(backfill_jobs):
                if i < batch_size:
                    # Queue immediately
                    enqueue_job('queue:content_generation', job)
                    logger.info(f"Queued backfill job {i+1} (immediate)")
                else:
                    # Queue with delay
                    # Note: Redis doesn't support delayed jobs natively
                    # We enqueue immediately but worker will process sequentially
                    enqueue_job('queue:content_generation', job)
                    logger.info(f"Queued backfill job {i+1} (will be delayed by worker)")
            
            logger.info(f"✅ Queued {len(backfill_jobs)} backfill AI jobs")
        
    except Exception as e:
        logger.error(f"Update daily stats failed: {e}")


# ============================================================================
# UPDATE MOVIE TOTALS
# ============================================================================

def update_movie_totals(movie_id: str, movie_title: str, totals: Dict):
    """
    Update movie's india_gross_total and overseas_total
    """
    try:
        update_data = {}
        
        if totals.get('india_gross_total') is not None:
            update_data['india_gross_total'] = totals['india_gross_total']
        
        if totals.get('overseas_total') is not None:
            update_data['overseas_total'] = totals['overseas_total']
        
        if update_data:
            directus_patch(f"/items/movies/{movie_id}", update_data)
            logger.info(f"Updated totals: India Gross=₹{totals.get('india_gross_total', 0)} Cr, Overseas=₹{totals.get('overseas_total', 0)} Cr")
        
    except Exception as e:
        logger.error(f"Update movie totals failed: {e}")


# ============================================================================
# RETRY FAILED JOBS
# ============================================================================

def retry_failed_jobs():
    """
    Retry failed jobs from previous runs
    """
    try:
        failed_jobs = get_failed_jobs()
        
        if not failed_jobs:
            return
        
        logger.info(f"Retrying {len(failed_jobs)} failed jobs")
        
        for job in failed_jobs:
            enqueue_job('queue:content_generation', job)
            logger.info(f"Re-queued: {job.get('type')}")
        
    except Exception as e:
        logger.error(f"Retry failed jobs error: {e}")


# ============================================================================
# MAIN SCRAPER WORKFLOW
# ============================================================================

def scrape_all_running_movies():
    """
    Scrape all running movies
    """
    logger.info("=" * 60)
    logger.info("SCRAPER: RUNNING MOVIES")
    logger.info("=" * 60)
    
    try:
        # Get all running movies
        result = directus_get("/items/movies?filter[status][_eq]=running&limit=1000&fields=*")
        running_movies = result.get('data', [])
        
        if not running_movies:
            logger.info("No running movies found")
            return
        
        logger.info(f"Found {len(running_movies)} running movies")
        
        success_count = 0
        fail_count = 0
        
        for movie in running_movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                release_date = movie.get('release_date')
                
                logger.info(f"\n{'=' * 40}")
                logger.info(f"Processing: {title}")
                logger.info(f"{'=' * 40}")
                
                # Scrape movie
                scraped_data = scrape_movie(movie)
                
                if not scraped_data:
                    logger.warning(f"Scraping failed for {title}")
                    fail_count += 1
                    continue
                
                # Update daily stats
                update_daily_stats(
                    movie_id,
                    title,
                    release_date,
                    scraped_data['days']
                )
                
                # Update movie totals
                update_movie_totals(
                    movie_id,
                    title,
                    scraped_data['totals']
                )
                
                success_count += 1
                logger.info(f"✅ Completed: {title}")
                
                # Anti-bot delay
                delay = random.uniform(3, 7)
                logger.info(f"Sleeping {delay:.1f}s...")
                time.sleep(delay)
                
            except Exception as e:
                logger.error(f"Error processing {title}: {e}")
                fail_count += 1
                continue
        
        logger.info(f"\nScraping complete:")
        logger.info(f"  - Success: {success_count}")
        logger.info(f"  - Failed: {fail_count}")
        
        # Retry failed jobs
        retry_failed_jobs()
        
    except Exception as e:
        logger.error(f"Scraper workflow failed: {e}")
    
    logger.info("=" * 60)


# ============================================================================
# SCHEDULER FOR COOLIFY
# ============================================================================

def run_scraper_job():
    """Wrapper for scheduled execution"""
    try:
        logger.info("Scheduled scraper job triggered")
        scrape_all_running_movies()
    except Exception as e:
        logger.error(f"Scheduled scraper job failed: {e}")


if __name__ == "__main__":
    # Schedule every 4 hours (configurable)
    interval_hours = get_setting("scraper_interval_hours", 4)
    
    schedule.every(interval_hours).hours.do(run_scraper_job)
    
    # Run once immediately on startup
    logger.info("Running scraper immediately on startup...")
    run_scraper_job()
    
    # Keep script running
    logger.info(f"Scraper scheduler started. Running every {interval_hours} hours")
    logger.info("Press Ctrl+C to stop")
    
    while True:
        schedule.run_pending()
        time_module.sleep(60)