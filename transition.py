"""
transition.py - Transition movies to running + Create hub + All missing day pages
Runs: Daily at 12:05 AM IST
"""

import sys
import os
from common import *
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time
import random
import schedule
import time as time_module

# ============================================================================
# HUB CONTENT GENERATION
# ============================================================================

def generate_hub_content(movie: Dict) -> Dict:
    """
    Generate box office hub page content (3 stages: Gen → Humanize → SEO)
    Returns: {main_content, meta_title, meta_description}
    """
    try:
        logger.info(f"Generating hub content for: {movie.get('title')}")
        
        # Build context
        title = movie.get('title', '')
        release_date = movie.get('release_date', '')
        plot = movie.get('plot', '')
        budget = movie.get('budget')
        languages = ', '.join(movie.get('language', []))
        genres = ', '.join(movie.get('genre', []))
        advance_booking = movie.get('advance_booking_total', 0)
        
        # Get cast names
        cast_names = []
        if movie.get('cast_crew'):
            for person_id in movie['cast_crew'][:5]:
                try:
                    result = directus_get(f"/items/people/{person_id}")
                    person_name = result.get('data', {}).get('name')
                    if person_name:
                        cast_names.append(person_name)
                except:
                    pass
        
        cast_text = ', '.join(cast_names) if cast_names else "Star cast"
        
        # STAGE 1: Generation
        model = get_setting("hub_generation_model", "anthropic/claude-3.5-sonnet")
        temperature = get_setting("hub_generation_temperature", 0.7)
        max_tokens = get_setting("hub_generation_max_tokens", 4000)
        
        prompt = f"""Generate a comprehensive box office hub overview page for this movie.

MOVIE DETAILS:
- Title: {title}
- Release Date: {release_date}
- Languages: {languages}
- Genres: {genres}
- Cast: {cast_text}
- Budget: ₹{budget} Cr
- Plot: {plot}
- Advance Booking: ₹{advance_booking} Cr (if available)

GENERATE 800-1000 word hub page with:
1. Introduction (movie overview)
2. Cast and crew highlights
3. Pre-release buzz and expectations
4. Advance booking analysis (if data available)
5. Expected performance
6. Day-wise collection tracking info
7. Key factors affecting box office

Return only the article text (not HTML yet)."""
        
        draft = call_openrouter(model, prompt, temperature, max_tokens)
        
        if not draft:
            raise Exception("Generation failed")
        
        # STAGE 2: Humanization
        humanize_model = get_setting("hub_humanize_model", "anthropic/claude-3.5-sonnet")
        humanize_temp = get_setting("hub_humanize_temperature", 0.8)
        humanize_tokens = get_setting("hub_humanize_max_tokens", 4000)
        
        humanize_prompt = f"""Rewrite this hub content to sound more natural and human.

CONTENT:
{draft}

Requirements:
- Remove AI-like phrases
- Make it engaging and professional
- Keep all facts intact

Return only the rewritten content."""
        
        humanized = call_openrouter(humanize_model, humanize_prompt, humanize_temp, humanize_tokens)
        
        if not humanized:
            logger.warning("Humanization failed, using draft")
            humanized = draft
        
        # STAGE 3: SEO
        seo_model = get_setting("hub_seo_model", "openai/gpt-4-turbo")
        seo_temp = get_setting("hub_seo_temperature", 0.5)
        seo_tokens = get_setting("hub_seo_max_tokens", 2000)
        
        seo_prompt = f"""Optimize this hub content for SEO.

TITLE: {title} Box Office Collection

CONTENT:
{humanized}

Return ONLY JSON:
{{
  "main_content": "<h1>...</h1><p>...</p>...",
  "meta_title": "...",
  "meta_description": "..."
}}"""
        
        result = call_openrouter(seo_model, seo_prompt, seo_temp, seo_tokens)
        
        if result:
            hub_data = extract_json_from_text(result)
            if hub_data:
                logger.info("Hub content generated successfully (3 stages)")
                return hub_data
        
        # Fallback
        logger.warning("SEO failed, using humanized content")
        return {
            "main_content": humanized,
            "meta_title": f"{title} Box Office Collection Day Wise",
            "meta_description": f"Track {title} box office collection day wise with detailed analysis."
        }
        
    except Exception as e:
        logger.error(f"Hub content generation failed: {e}")
        
        return {
            "main_content": f"<h1>{movie.get('title')} Box Office Collection</h1><p>Track day-wise box office performance here.</p>",
            "meta_title": f"{movie.get('title')} Box Office Collection",
            "meta_description": f"Track {movie.get('title')} box office collection day wise."
        }


# ============================================================================
# BOX OFFICE HUB CREATION
# ============================================================================

def create_box_office_hub(movie_id: str, movie: Dict) -> Optional[str]:
    """
    Create box_office_hubs entry
    Returns: hub_id or None
    """
    try:
        logger.info(f"Creating box office hub for: {movie.get('title')}")
        
        # Generate hub content
        hub_content = generate_hub_content(movie)
        
        # Generate tags
        tags = [movie.get('title', ''), 'box office']
        if movie.get('language'):
            tags.extend(movie['language'])
        
        # Create hub
        hub_payload = {
            'movie_id': movie_id,
            'slug': slugify(f"{movie.get('title', '')}-box-office-collection"),
            'main_content': hub_content.get('main_content', ''),
            'tags': tags
        }
        
        result = directus_post('/items/box_office_hubs', hub_payload)
        hub_id = result.get('data', {}).get('id')
        
        logger.info(f"Hub created: {hub_id}")
        return hub_id
        
    except Exception as e:
        logger.error(f"Hub creation failed: {e}")
        return None


# ============================================================================
# DAILY STATS PAGE CREATION (PREDICTION MODE)
# ============================================================================

def create_daily_stats_page(movie_id: str, movie: Dict, day_number: int, date: str) -> Optional[str]:
    """
    Create single daily_stats entry with empty content
    Returns: daily_stats_id or None
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
            'date': date,
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
        logger.error(f"Daily stats creation failed for Day {day_number}: {e}")
        return None


# ============================================================================
# BULK DAY PAGE CREATION
# ============================================================================

def create_all_missing_day_pages(movie_id: str, movie: Dict, release_date: str, today_str: str):
    """
    Create ALL missing day pages from release date to today
    Queue AI jobs for each
    """
    try:
        release = datetime.strptime(release_date, "%Y-%m-%d")
        today = datetime.strptime(today_str, "%Y-%m-%d")
        
        # Calculate current day number
        current_day = (today - release).days + 1
        
        logger.info(f"Creating day pages 1 to {current_day} for {movie.get('title')}")
        
        # Check which days already exist
        existing_result = directus_get(
            f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&fields=day_number&limit=1000"
        )
        existing_days = [d['day_number'] for d in existing_result.get('data', [])]
        
        created_count = 0
        
        # Create missing days
        for day in range(1, current_day + 1):
            if day in existing_days:
                logger.info(f"Day {day} already exists, skipping")
                continue
            
            # Calculate date for this day
            day_date = release + timedelta(days=day - 1)
            day_date_str = day_date.strftime("%Y-%m-%d")
            
            # Create page
            stats_id = create_daily_stats_page(movie_id, movie, day, day_date_str)
            
            if stats_id:
                created_count += 1
                
                # Queue AI content generation job
                job_data = {
                    'type': 'daily_box_office_prediction',
                    'movie_id': movie_id,
                    'day_number': day,
                    'movie_title': movie.get('title'),
                    'mode': 'prediction'
                }
                
                enqueue_job('queue:content_generation', job_data)
                logger.info(f"AI job queued for Day {day}")
            
            # Small delay
            time.sleep(0.5)
        
        logger.info(f"Created {created_count} day pages, queued {created_count} AI jobs")
        
    except Exception as e:
        logger.error(f"Bulk day page creation failed: {e}")


# ============================================================================
# SLACK NOTIFICATION
# ============================================================================

def send_transition_notification(movie: Dict, created_days: int):
    """Send Slack notification for movie transition"""
    try:
        title = movie.get('title')
        release_date = movie.get('release_date')
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚀 MOVIE NOW RUNNING"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Movie:* {title}\n*Release:* {release_date}\n*Status:* announced → running"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Created:*\n✅ Box office hub page\n✅ {created_days} day collection pages\n✅ {created_days} AI content jobs queued"
                }
            }
        ]
        
        slack_post_message(blocks, f"Movie running: {title}")
        
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")


# ============================================================================
# MAIN TRANSITION WORKFLOW
# ============================================================================

def transition_movies_to_running():
    """
    Transition movies from announced to running
    1 day before release or on release day
    """
    logger.info("=" * 60)
    logger.info("TRANSITION: ANNOUNCED → RUNNING")
    logger.info("=" * 60)
    
    try:
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        tomorrow = today + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        
        # Query movies to transition
        # 1 day before (release_date = tomorrow) OR release day (release_date = today)
        result = directus_get(
            f"/items/movies?filter[status][_eq]=announced&filter[_or][0][release_date][_eq]={today_str}&filter[_or][1][release_date][_eq]={tomorrow_str}&limit=100"
        )
        
        movies_to_transition = result.get('data', [])
        
        if not movies_to_transition:
            logger.info("No movies to transition")
            return
        
        logger.info(f"Found {len(movies_to_transition)} movies to transition")
        
        for movie in movies_to_transition:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                release_date = movie.get('release_date')
                
                logger.info(f"\n{'=' * 40}")
                logger.info(f"Transitioning: {title}")
                logger.info(f"Release: {release_date}")
                logger.info(f"{'=' * 40}")
                
                # Update status to running
                directus_patch(f"/items/movies/{movie_id}", {'status': 'running'})
                logger.info("✅ Status updated to 'running'")
                
                # Create box office hub
                hub_id = create_box_office_hub(movie_id, movie)
                if hub_id:
                    logger.info("✅ Hub created")
                
                # Create ALL missing day pages
                create_all_missing_day_pages(movie_id, movie, release_date, today_str)
                
                # Calculate how many days were created
                current_day = calculate_day_number(release_date, today_str)
                
                # Send Slack notification
                send_transition_notification(movie, current_day)
                
                logger.info(f"✅ Transition complete for {title}")
                
                # Rate limiting
                time.sleep(random.uniform(2, 4))
                
            except Exception as e:
                logger.error(f"Error transitioning movie {title}: {e}")
                continue
        
        logger.info(f"\nTransition workflow complete")
        
    except Exception as e:
        logger.error(f"Transition workflow failed: {e}")
    
    logger.info("=" * 60)


# ============================================================================
# SCHEDULER FOR COOLIFY
# ============================================================================

def run_transition_job():
    """Wrapper for scheduled execution"""
    try:
        logger.info("Scheduled transition job triggered")
        transition_movies_to_running()
    except Exception as e:
        logger.error(f"Scheduled transition job failed: {e}")


if __name__ == "__main__":
    import schedule
    import time as time_module
    
    # Schedule daily at 12:05 AM IST (runs after discovery.py)
    schedule.every().day.at("00:05").do(run_transition_job)
    
    # Keep script running
    logger.info("Transition scheduler started. Running daily at 00:05 IST")
    logger.info("Press Ctrl+C to stop")
    
    while True:
        schedule.run_pending()
        time_module.sleep(60)