"""
daily_pages.py - Create today's day page for running movies
Runs: Daily at 12:05 AM IST
"""

import sys
import os
from common import *
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import time
import random
import schedule
import time as time_module


# ============================================================================
# 2-DAY GAP CHECK (MOVIE CLOSING LOGIC)
# ============================================================================

def check_movie_still_tracked(movie: Dict) -> bool:
    """
    Check if Sacnilk is still updating this movie
    Returns: True if still active, False if should close
    """
    try:
        sacnilk_url = movie.get('sacnilk_source_url')
        release_date = movie.get('release_date')
        
        if not sacnilk_url or not release_date:
            return True  # Can't check, assume active
        
        logger.info(f"Checking if {movie.get('title')} still tracked on Sacnilk")
        
        # Scrape Sacnilk page
        response = requests.get(sacnilk_url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find box office table
        # NOTE: Adjust selector based on actual HTML structure
        table = soup.find('table', class_='box-office-table')  # Placeholder
        
        if not table:
            logger.warning("Could not find box office table")
            return True  # Assume active if can't parse
        
        # Count rows (days)
        rows = table.find_all('tr')[1:]  # Skip header
        actual_days = len(rows)
        
        # Calculate expected days
        release = datetime.strptime(release_date, "%Y-%m-%d")
        today = datetime.now()
        expected_days = (today - release).days + 1
        
        gap = expected_days - actual_days
        
        logger.info(f"Expected days: {expected_days}, Actual days: {actual_days}, Gap: {gap}")
        
        # If gap >= 2, movie has stopped updating
        if gap >= 2:
            logger.warning(f"2-day gap detected! Movie should be closed.")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error checking movie tracking: {e}")
        return True  # Assume active on error


# ============================================================================
# MOVIE CLOSING + VERDICT CALCULATION
# ============================================================================

def close_movie_and_calculate_verdict(movie_id: str, movie: Dict):
    """
    Close movie and calculate final verdict
    """
    try:
        title = movie.get('title')
        logger.info(f"Closing movie: {title}")
        
        # Calculate verdict
        budget = movie.get('budget')
        india_gross = movie.get('india_gross_total', 0)
        
        verdict = 'pending'
        
        if budget and budget > 0 and india_gross > 0:
            roi = india_gross / budget
            
            if roi >= 5:
                verdict = 'blockbuster'
            elif roi >= 3:
                verdict = 'hit'
            elif roi >= 2:
                verdict = 'average'
            elif roi >= 1:
                verdict = 'flop'
            else:
                verdict = 'disaster'
            
            logger.info(f"Verdict calculated: {verdict} (ROI: {roi:.2f}x)")
        else:
            logger.warning("Cannot calculate verdict - missing budget or collection data")
        
        # Update movie
        directus_patch(f"/items/movies/{movie_id}", {
            'status': 'closed',
            'verdict': verdict
        })
        
        # Calculate total days
        release_date = movie.get('release_date')
        if release_date:
            release = datetime.strptime(release_date, "%Y-%m-%d")
            total_days = (datetime.now() - release).days + 1
        else:
            total_days = 0
        
        # Send Slack notification
        send_movie_closed_notification(movie, verdict, total_days)
        
        logger.info(f"✅ Movie closed: {title} - Verdict: {verdict}")
        
    except Exception as e:
        logger.error(f"Error closing movie: {e}")


def send_movie_closed_notification(movie: Dict, verdict: str, total_days: int):
    """Send Slack notification for closed movie"""
    try:
        title = movie.get('title')
        india_gross = movie.get('india_gross_total', 0)
        budget = movie.get('budget', 0)
        
        verdict_emoji = {
            'blockbuster': '🎉',
            'hit': '✅',
            'average': '😐',
            'flop': '📉',
            'disaster': '💥',
            'pending': '⏳'
        }.get(verdict, '🏁')
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🏁 MOVIE CLOSED"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Title:* {title}\n*Total Days:* {total_days}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Final Collection:* ₹{india_gross} Cr (India Gross)\n*Budget:* ₹{budget} Cr\n*Verdict:* {verdict.upper()} {verdict_emoji}"
                }
            }
        ]
        
        if budget > 0:
            roi = india_gross / budget
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*ROI:* {roi:.2f}x"
                }
            })
        
        slack_post_message(blocks, f"Movie closed: {title}")
        
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")


# ============================================================================
# DAILY STATS PAGE CREATION
# ============================================================================

def create_todays_page(movie_id: str, movie: Dict, day_number: int, date_str: str) -> Optional[str]:
    """
    Create daily_stats entry for today
    Returns: stats_id or None
    """
    try:
        logger.info(f"Creating Day {day_number} page for {movie.get('title')}")
        
        # Generate tags
        tags = [
            movie.get('title', ''),
            f"day {day_number}",
            'box office collection'
        ]
        
        # Create daily_stats entry
        stats_payload = {
            'movie_id': movie_id,
            'day_number': day_number,
            'date': date_str,
            'india_net': 0,  # Placeholder
            'is_estimate': True,
            'seo_content': '',  # Empty - AI fills later
            'slug': slugify(f"{movie.get('title', '')}-day-{day_number}-box-office-collection"),
            'tags': tags
        }
        
        result = directus_post('/items/daily_stats', stats_payload)
        stats_id = result.get('data', {}).get('id')
        
        logger.info(f"Day {day_number} page created: {stats_id}")
        return stats_id
        
    except Exception as e:
        logger.error(f"Daily stats creation failed: {e}")
        return None


# ============================================================================
# MAIN DAILY PAGE WORKFLOW
# ============================================================================

def create_daily_pages():
    """
    Create today's day page for all running movies
    """
    logger.info("=" * 60)
    logger.info("DAILY PAGE CREATION")
    logger.info("=" * 60)
    
    try:
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        
        # Get all running movies
        result = directus_get("/items/movies?filter[status][_eq]=running&limit=1000")
        running_movies = result.get('data', [])
        
        if not running_movies:
            logger.info("No running movies found")
            return
        
        logger.info(f"Found {len(running_movies)} running movies")
        
        created_count = 0
        closed_count = 0
        
        for movie in running_movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                release_date = movie.get('release_date')
                
                logger.info(f"\n{'=' * 40}")
                logger.info(f"Processing: {title}")
                logger.info(f"{'=' * 40}")
                
                # Calculate day number
                day_number = calculate_day_number(release_date, today_str)
                
                logger.info(f"Today is Day {day_number}")
                
                # Check if page already exists
                existing = directus_get(
                    f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[day_number][_eq]={day_number}&limit=1"
                )
                
                if existing.get('data') and len(existing['data']) > 0:
                    logger.info(f"Day {day_number} page already exists, skipping")
                    continue
                
                # 2-day gap check (should we close the movie?)
                still_tracked = check_movie_still_tracked(movie)
                
                if not still_tracked:
                    # Close movie
                    close_movie_and_calculate_verdict(movie_id, movie)
                    closed_count += 1
                    continue
                
                # Create today's page
                stats_id = create_todays_page(movie_id, movie, day_number, today_str)
                
                if stats_id:
                    created_count += 1
                    
                    # Queue AI content generation job
                    job_data = {
                        'type': 'daily_box_office_prediction',
                        'movie_id': movie_id,
                        'day_number': day_number,
                        'movie_title': title,
                        'mode': 'prediction'
                    }
                    
                    enqueue_job('queue:content_generation', job_data)
                    logger.info(f"✅ AI job queued for Day {day_number}")
                
                # Rate limiting
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                logger.error(f"Error processing movie {title}: {e}")
                
                # Store failed job for retry
                store_failed_job({
                    'type': 'daily_page_creation',
                    'movie_id': movie_id,
                    'movie_title': title,
                    'day_number': day_number,
                    'date': today_str
                })
                
                continue
        
        logger.info(f"\nDaily page creation complete:")
        logger.info(f"  - Created: {created_count} pages")
        logger.info(f"  - Closed: {closed_count} movies")
        
    except Exception as e:
        logger.error(f"Daily page workflow failed: {e}")
    
    logger.info("=" * 60)


# ============================================================================
# SCHEDULER FOR COOLIFY
# ============================================================================

def run_daily_pages_job():
    """Wrapper for scheduled execution"""
    try:
        logger.info("Scheduled daily pages job triggered")
        create_daily_pages()
    except Exception as e:
        logger.error(f"Scheduled daily pages job failed: {e}")


if __name__ == "__main__":
    # Schedule daily at 12:05 AM IST
    schedule.every().day.at("00:05").do(run_daily_pages_job)
    
    # Keep script running
    logger.info("Daily pages scheduler started. Running daily at 00:05 IST")
    logger.info("Press Ctrl+C to stop")
    
    while True:
        schedule.run_pending()
        time_module.sleep(60)