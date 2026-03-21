"""
auditor.py - Nightly auditor to correct estimates + update totals
Runs: Daily at 3:00 AM IST
Corrects: Past 3 days estimates only
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
# PLAYWRIGHT SETUP (REUSE FROM SCRAPER)
# ============================================================================

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not available, using requests fallback")


def get_page_content(url: str) -> Optional[str]:
    """
    Fetch page content (same as scraper.py)
    """
    if PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                proxies = get_setting("scraper_proxies", [])
                proxy_config = None
                
                if proxies:
                    proxy = random.choice(proxies)
                    proxy_config = {"server": proxy}
                
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
    """
    Parse Sacnilk box office table (same as scraper.py)
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        table = soup.find('table', class_='box-office-table') or soup.find('table')
        
        if not table:
            logger.error("Could not find box office table")
            return None
        
        rows = table.find_all('tr')
        
        if len(rows) < 2:
            return None
        
        # Parse header
        header = rows[0]
        headers = [th.text.strip().lower() for th in header.find_all(['th', 'td'])]
        
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
            elif 'overseas' in h:
                overseas_idx = i
        
        # Parse data rows
        days_data = []
        
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            
            if len(cells) < 2:
                continue
            
            first_cell = cells[0].text.strip().lower()
            if 'total' in first_cell:
                continue
            
            day_text = cells[day_idx].text.strip() if day_idx is not None else cells[0].text.strip()
            day_match = re.search(r'(\d+)', day_text)
            
            if not day_match:
                continue
            
            day_number = int(day_match.group(1))
            
            india_net = 0
            if india_net_idx is not None and india_net_idx < len(cells):
                india_net_text = cells[india_net_idx].text.strip()
                india_net = parse_number_from_text(india_net_text) or 0
            
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
                if india_gross_idx is not None and india_gross_idx < len(cells):
                    india_gross_text = cells[india_gross_idx].text.strip()
                    totals['india_gross_total'] = parse_number_from_text(india_gross_text) or 0
                
                if overseas_idx is not None and overseas_idx < len(cells):
                    overseas_text = cells[overseas_idx].text.strip()
                    totals['overseas_total'] = parse_number_from_text(overseas_text) or 0
                
                break
        
        return {
            'days': days_data,
            'totals': totals
        }
        
    except Exception as e:
        logger.error(f"Table parsing failed: {e}")
        return None


# ============================================================================
# CORRECT ESTIMATES (PAST 3 DAYS)
# ============================================================================

def correct_estimates_for_movie(movie: Dict):
    """
    Correct estimates for past 3 days for a single movie
    """
    try:
        movie_id = movie['id']
        title = movie.get('title')
        sacnilk_url = movie.get('sacnilk_source_url')
        
        if not sacnilk_url:
            logger.warning(f"No Sacnilk URL for {title}")
            return
        
        logger.info(f"Correcting estimates: {title}")
        
        today = datetime.now().date()
        three_days_ago = today - timedelta(days=3)
        
        # Get estimates from past 3 days (not today)
        estimates_result = directus_get(
            f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[is_estimate][_eq]=true&filter[date][_gte]={three_days_ago.strftime('%Y-%m-%d')}&filter[date][_lt]={today.strftime('%Y-%m-%d')}&limit=100"
        )
        
        estimates = estimates_result.get('data', [])
        
        if not estimates:
            logger.info(f"No estimates to correct for {title}")
            return
        
        logger.info(f"Found {len(estimates)} estimates to correct")
        
        # Scrape current data
        html_content = get_page_content(sacnilk_url)
        
        if not html_content:
            logger.error(f"Failed to fetch content for {title}")
            return
        
        parsed_data = parse_box_office_table(html_content)
        
        if not parsed_data:
            logger.error(f"Failed to parse table for {title}")
            return
        
        # Create lookup dict
        actual_data = {day['day_number']: day for day in parsed_data['days']}
        
        corrected_count = 0
        
        # Correct each estimate
        for estimate in estimates:
            day_number = estimate['day_number']
            
            if day_number not in actual_data:
                logger.warning(f"Day {day_number} not found in scraped data")
                continue
            
            actual = actual_data[day_number]
            old_value = estimate.get('india_net', 0)
            new_value = actual['india_net']
            
            # Update with actuals
            directus_patch(f"/items/daily_stats/{estimate['id']}", {
                'india_net': new_value,
                'is_estimate': False
            })
            
            logger.info(f"Corrected Day {day_number}: ₹{old_value} → ₹{new_value} Cr")
            corrected_count += 1
        
        # Update movie totals
        if parsed_data.get('totals'):
            update_data = {}
            
            if parsed_data['totals'].get('india_gross_total') is not None:
                update_data['india_gross_total'] = parsed_data['totals']['india_gross_total']
            
            if parsed_data['totals'].get('overseas_total') is not None:
                update_data['overseas_total'] = parsed_data['totals']['overseas_total']
            
            if update_data:
                directus_patch(f"/items/movies/{movie_id}", update_data)
                logger.info(f"Updated movie totals")
        
        logger.info(f"✅ Corrected {corrected_count} estimates for {title}")
        
    except Exception as e:
        logger.error(f"Error correcting estimates for {title}: {e}")


# ============================================================================
# MAIN AUDITOR WORKFLOW
# ============================================================================

def run_nightly_audit():
    """
    Run nightly audit on all running movies
    """
    logger.info("=" * 60)
    logger.info("NIGHTLY AUDITOR")
    logger.info("=" * 60)
    
    try:
        # Get all running movies
        result = directus_get("/items/movies?filter[status][_eq]=running&limit=1000&fields=*")
        running_movies = result.get('data', [])
        
        if not running_movies:
            logger.info("No running movies found")
            return
        
        logger.info(f"Found {len(running_movies)} running movies")
        
        processed_count = 0
        
        for movie in running_movies:
            try:
                correct_estimates_for_movie(movie)
                processed_count += 1
                
                # Anti-bot delay
                delay = random.uniform(2, 5)
                logger.info(f"Sleeping {delay:.1f}s...")
                time.sleep(delay)
                
            except Exception as e:
                logger.error(f"Error processing movie: {e}")
                continue
        
        logger.info(f"\nAudit complete: {processed_count} movies processed")
        
    except Exception as e:
        logger.error(f"Auditor workflow failed: {e}")
    
    logger.info("=" * 60)


# ============================================================================
# SCHEDULER FOR COOLIFY
# ============================================================================

def run_auditor_job():
    """Wrapper for scheduled execution"""
    try:
        logger.info("Scheduled auditor job triggered")
        run_nightly_audit()
    except Exception as e:
        logger.error(f"Scheduled auditor job failed: {e}")


if __name__ == "__main__":
    # Schedule daily at 3:00 AM IST
    schedule.every().day.at("03:00").do(run_auditor_job)
    
    # Keep script running
    logger.info("Auditor scheduler started. Running daily at 03:00 IST")
    logger.info("Press Ctrl+C to stop")
    
    while True:
        schedule.run_pending()
        time_module.sleep(60)