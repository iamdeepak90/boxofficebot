"""
scheduler.py - All scheduled automation tasks
Runs:
- 00:05 AM: Discovery + Transition + Daily Pages
- 03:00 AM: Audit estimates
- Every 4 hours: Scraper
- Every 5 minutes: RSS feeds
"""

import sys
import os
from common import *
from datetime import datetime, timedelta
import time
import random
import schedule
import feedparser

# ============================================================================
# DISCOVERY (00:05 AM)
# ============================================================================

def discover_new_movies():
    """Scrape Sacnilk upcoming and create new movies"""
    logger.info("=" * 60)
    logger.info("DISCOVERY: NEW MOVIES")
    logger.info("=" * 60)
    
    try:
        movies = scrape_sacnilk_upcoming()
        
        if not movies:
            logger.info("No movies found on upcoming page")
            return
        
        logger.info(f"Found {len(movies)} movies on upcoming page")
        
        created_count = 0
        
        for movie_data in movies:
            try:
                title = movie_data.get('title')
                sacnilk_url = movie_data.get('sacnilk_source_url')
                
                if not title or not sacnilk_url:
                    continue
                
                logger.info(f"Processing: {title}")
                
                # Check duplicate
                duplicate = check_duplicate_movie(title, sacnilk_url)
                
                if duplicate:
                    similarity = fuzzy_match(title, duplicate.get('title', ''))
                    logger.warning(f"Duplicate found: {duplicate.get('title')} ({similarity}%)")
                    send_duplicate_alert_slack(title, duplicate.get('title'), similarity, sacnilk_url)
                    continue
                
                # Scrape full details
                details = scrape_movie_details(sacnilk_url)
                if details:
                    movie_data.update(details)
                
                # Process cast from details (merged casts from scrape_movie_details)
                cast_ids = []
                for person_data in movie_data.get('casts', []):
                    person_id = get_or_create_person(person_data['name'], person_data['type'])
                    if person_id:
                        cast_ids.append(person_id)
                
                # Humanize summary (2 stages: Gen → Humanize)
                raw_summary = movie_data.get('summary', '')
                if raw_summary:
                    humanized_plot = humanize_plot(raw_summary, title)
                    movie_data['plot'] = humanized_plot
                
                # Upload poster
                poster_url = movie_data.get('poster_url')
                if poster_url:
                    poster_uuid = upload_file_to_directus(file_url=poster_url, title=slugify(title))
                    if poster_uuid:
                        movie_data['poster'] = poster_uuid
                
                # Create movie
                create_data = {
                    'status': 'announced',
                    'title': title,
                    'slug': movie_data.get('slug'),
                    'release_date': movie_data.get('release_date'),
                    'language': movie_data.get('languages', []),
                    'genre': movie_data.get('genres', ''),
                    'sacnilk_source_url': sacnilk_url,
                    'poster': movie_data.get('poster'),
                    'budget': movie_data.get('budget', 0),
                    'plot': movie_data.get('plot', ''),
                    'runtime': movie_data.get('runtime'),
                    'cbfc_rating': movie_data.get('cbfc_rating'),
                    'ott_platform': movie_data.get('ott_platform'),
                    'ott_release_date': movie_data.get('ott_release_date'),
                    'cast_crew': cast_ids,
                    'tags': movie_data.get('tags', []) + movie_data.get('genres', [])
                }
                
                result = directus_post('/items/movies', create_data)
                movie_id = result.get('data', {}).get('id')
                
                if movie_id:
                    logger.info(f"✅ Created movie: {title} ({movie_id})")
                    created_count += 1
                    send_new_movie_notification(movie_data, movie_id)
                
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                logger.error(f"Error processing {title}: {e}")
                continue
        
        logger.info(f"Discovery complete: {created_count} movies created")
        
    except Exception as e:
        logger.error(f"Discovery failed: {e}")


def humanize_plot(raw_plot: str, movie_title: str) -> str:
    """Humanize plot (2 stages: Gen → Humanize, NO SEO)"""
    try:
        if not raw_plot:
            return ""
        
        prompt = f"""Rewrite this movie plot in 2-3 engaging paragraphs.

Movie: {movie_title}

Raw Plot:
{raw_plot}

Requirements:
- Engaging and natural
- Clear, concise language
- Avoid spoilers
- 150-200 words

Return only the rewritten plot."""
        
        draft = stage_generation(prompt, 'plot')
        if not draft:
            return raw_plot
        
        humanized = stage_humanize(draft, 'plot')
        if humanized:
            return humanized
        
        return draft
        
    except Exception as e:
        logger.error(f"Plot humanization failed: {e}")
        return raw_plot


def send_new_movie_notification(movie_data: Dict, movie_id: str):
    """Send Slack notification for new movie"""
    try:
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🎬 NEW MOVIE DISCOVERED"}
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Title:* {movie_data.get('title')}\n*Release:* {movie_data.get('release_date')}\n*Budget:* ₹{movie_data.get('budget', 0)} Cr\n*ID:* {movie_id}"
                }
            }
        ]
        
        slack_post_message(blocks, f"New movie: {movie_data.get('title')}")
        
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")


def update_announced_movies():
    """Update metadata for announced movies until Day 3"""
    logger.info("=" * 60)
    logger.info("UPDATE: ANNOUNCED MOVIES")
    logger.info("=" * 60)
    
    try:
        today = datetime.now().date()
        three_days_ago = (today - timedelta(days=3)).strftime('%Y-%m-%d')
        
        # Get announced movies + running movies released within 3 days
        result = directus_get(
            f"/items/movies?filter[_or][0][status][_eq]=announced&filter[_or][1][_and][0][status][_eq]=running&filter[_or][1][_and][1][release_date][_gte]={three_days_ago}&limit=100"
        )
        
        movies = result.get('data', [])
        
        if not movies:
            logger.info("No movies to update")
            return
        
        logger.info(f"Updating {len(movies)} movies")
        
        for movie in movies:
            try:
                title = movie.get('title')
                sacnilk_url = movie.get('sacnilk_source_url')
                
                logger.info(f"Updating: {title}")
                
                # Scrape fresh data
                details = scrape_movie_details(sacnilk_url)
                
                if not details:
                    continue
                
                # Merge cast (additive)
                existing_cast = movie.get('cast_crew', [])
                new_cast_names = details.get('cast_names', [])
                
                for name in new_cast_names:
                    person_id = get_or_create_person(name, 'actor')
                    if person_id and person_id not in existing_cast:
                        existing_cast.append(person_id)
                
                # Update movie
                update_data = {
                    'language': details.get('language', movie.get('language', [])),
                    'genre': details.get('genre', movie.get('genre', [])),
                    'budget': details.get('budget', movie.get('budget')),
                    'cast_crew': existing_cast,
                    'advance_booking_total': details.get('advance_booking', movie.get('advance_booking_total', 0))
                }
                
                directus_patch(f"/items/movies/{movie['id']}", update_data)
                
                logger.info(f"✅ Updated: {title}")
                
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                logger.error(f"Error updating {title}: {e}")
                continue
        
        logger.info("Update complete")
        
    except Exception as e:
        logger.error(f"Update announced movies failed: {e}")

# ============================================================================
# TRANSITION (00:05 AM)
# ============================================================================

def transition_movies_to_running():
    """Transition announced → running, create hub + all day pages"""
    logger.info("=" * 60)
    logger.info("TRANSITION: ANNOUNCED → RUNNING")
    logger.info("=" * 60)
    
    try:
        today = datetime.now().date()
        tomorrow = (today + timedelta(days=1)).strftime('%Y-%m-%d')
        today_str = today.strftime('%Y-%m-%d')
        
        # Get movies releasing today or tomorrow
        result = directus_get(
            f"/items/movies?filter[status][_eq]=announced&filter[_or][0][release_date][_eq]={today_str}&filter[_or][1][release_date][_eq]={tomorrow}&limit=100"
        )
        
        movies = result.get('data', [])
        
        if not movies:
            logger.info("No movies to transition")
            return
        
        logger.info(f"Transitioning {len(movies)} movies")
        
        for movie in movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                release_date = movie.get('release_date')
                
                logger.info(f"Transitioning: {title}")
                
                # Update status
                directus_patch(f"/items/movies/{movie_id}", {'status': 'running'})
                
                # Generate hub content (3 stages: Gen → Humanize → SEO)
                hub_data = generate_hub_content(movie)
                
                # Create hub
                hub_payload = {
                    'movie_id': movie_id,
                    'main_content': hub_data.get('main_content', ''),
                    'meta_title': hub_data.get('meta_title', f"{title} Box Office Collection"),
                    'meta_description': hub_data.get('meta_description', ''),
                    'slug': slugify(f"{title}-box-office-collection"),
                    'tags': [title, 'box office collection']
                }
                
                directus_post('/items/box_office_hubs', hub_payload)
                
                # Create all day pages up to today
                current_day = calculate_day_number(release_date, today_str)
                
                for day in range(1, current_day + 1):
                    day_date = (datetime.strptime(release_date, '%Y-%m-%d') + timedelta(days=day - 1)).strftime('%Y-%m-%d')
                    
                    # Check if exists
                    existing = directus_get(
                        f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[day_number][_eq]={day}&limit=1"
                    )
                    
                    if existing.get('data'):
                        continue
                    
                    # Create page
                    stats_payload = {
                        'movie_id': movie_id,
                        'day_number': day,
                        'date': day_date,
                        'india_net': 0,
                        'is_estimate': True,
                        'seo_content': '',
                        'slug': slugify(f"{title}-day-{day}-box-office-collection"),
                        'tags': [title, f"day {day}", "box office"]
                    }
                    
                    result = directus_post('/items/daily_stats', stats_payload)
                    
                    if result.get('data'):
                        # Queue AI job
                        enqueue_job('queue:content_generation', {
                            'type': 'daily_box_office_prediction',
                            'movie_id': movie_id,
                            'day_number': day,
                            'movie_title': title,
                            'mode': 'prediction'
                        })
                
                logger.info(f"✅ Transitioned: {title} (created {current_day} day pages)")
                
                # Slack notification
                blocks = [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "🚀 MOVIE LIVE"}
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{title}*\nStatus: Running\nHub + {current_day} day pages created"
                        }
                    }
                ]
                
                slack_post_message(blocks, f"Movie live: {title}")
                
                time.sleep(random.uniform(2, 3))
                
            except Exception as e:
                logger.error(f"Error transitioning {title}: {e}")
                continue
        
        logger.info("Transition complete")
        
    except Exception as e:
        logger.error(f"Transition failed: {e}")


def generate_hub_content(movie: Dict) -> Dict:
    """Generate hub content (3 stages: Gen → Humanize → SEO)"""
    try:
        title = movie.get('title', '')
        release_date = movie.get('release_date', '')
        plot = movie.get('plot', '')
        budget = movie.get('budget', 0)
        languages = ', '.join(movie.get('language', []))
        genres = ', '.join(movie.get('genre', []))
        
        # Get cast names
        cast_names = []
        for person_id in movie.get('cast_crew', [])[:5]:
            result = directus_get(f"/items/people/{person_id}?fields=name")
            person = result.get('data', {})
            if person:
                cast_names.append(person.get('name', ''))
        
        cast_text = ', '.join(cast_names) if cast_names else "Star cast"
        
        # Stage 1: Generation
        prompt = f"""Generate a comprehensive box office hub page for this movie.

MOVIE DETAILS:
- Title: {title}
- Release Date: {release_date}
- Languages: {languages}
- Genres: {genres}
- Cast: {cast_text}
- Budget: ₹{budget} Cr
- Plot: {plot}

Generate 800-1000 word hub page with:
1. Introduction
2. Cast and crew highlights
3. Pre-release buzz
4. Expected performance
5. Day-wise tracking info

Return only the text (not HTML yet)."""
        
        draft = stage_generation(prompt, 'hub')
        if not draft:
            raise Exception("Generation failed")
        
        # Stage 2: Humanization
        humanized = stage_humanize(draft, 'hub')
        if not humanized:
            humanized = draft
        
        # Stage 3: SEO
        seo_data = stage_seo(humanized, f"{title} Box Office Collection", 'hub')
        
        if seo_data:
            return seo_data
        
        return {
            "main_content": humanized,
            "meta_title": f"{title} Box Office Collection Day Wise",
            "meta_description": f"Track {title} box office collection day wise."
        }
        
    except Exception as e:
        logger.error(f"Hub generation failed: {e}")
        return {
            "main_content": f"<h1>{movie.get('title')} Box Office Collection</h1>",
            "meta_title": f"{movie.get('title')} Box Office",
            "meta_description": ""
        }

# ============================================================================
# DAILY PAGES (00:05 AM)
# ============================================================================

def create_daily_pages():
    """Create today's page for running movies + close old ones"""
    logger.info("=" * 60)
    logger.info("DAILY PAGES: CREATE + CLOSE")
    logger.info("=" * 60)
    
    try:
        today = datetime.now().date()
        today_str = today.strftime('%Y-%m-%d')
        
        result = directus_get("/items/movies?filter[status][_eq]=running&limit=1000")
        running_movies = result.get('data', [])
        
        if not running_movies:
            logger.info("No running movies")
            return
        
        logger.info(f"Processing {len(running_movies)} running movies")
        
        created_count = 0
        closed_count = 0
        
        for movie in running_movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                release_date = movie.get('release_date')
                
                day_number = calculate_day_number(release_date, today_str)
                
                logger.info(f"{title}: Day {day_number}")
                
                # Check if page exists
                existing = directus_get(
                    f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[day_number][_eq]={day_number}&limit=1"
                )
                
                if existing.get('data'):
                    logger.info(f"Day {day_number} already exists")
                    continue
                
                # 2-day gap check
                still_tracked = check_movie_still_tracked(movie)
                
                if not still_tracked:
                    close_movie_and_calculate_verdict(movie_id, movie)
                    closed_count += 1
                    continue
                
                # Create today's page
                stats_payload = {
                    'movie_id': movie_id,
                    'day_number': day_number,
                    'date': today_str,
                    'india_net': 0,
                    'is_estimate': True,
                    'seo_content': '',
                    'slug': slugify(f"{title}-day-{day_number}-box-office-collection"),
                    'tags': [title, f"day {day_number}", "box office"]
                }
                
                result = directus_post('/items/daily_stats', stats_payload)
                
                if result.get('data'):
                    created_count += 1
                    
                    # Queue AI job
                    enqueue_job('queue:content_generation', {
                        'type': 'daily_box_office_prediction',
                        'movie_id': movie_id,
                        'day_number': day_number,
                        'movie_title': title,
                        'mode': 'prediction'
                    })
                    
                    logger.info(f"✅ Created Day {day_number} page")
                
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                logger.error(f"Error processing {title}: {e}")
                continue
        
        logger.info(f"Daily pages complete: {created_count} created, {closed_count} closed")
        
    except Exception as e:
        logger.error(f"Daily pages failed: {e}")


def check_movie_still_tracked(movie: Dict) -> bool:
    """Check if Sacnilk still tracking (2-day gap check)"""
    try:
        sacnilk_url = movie.get('sacnilk_source_url')
        release_date = movie.get('release_date')
        
        if not sacnilk_url or not release_date:
            return True
        
        html = get_page_content(sacnilk_url)
        if not html:
            return True
        
        parsed = parse_box_office_table(html)
        if not parsed:
            return True
        
        actual_days = len(parsed['days'])
        
        release = datetime.strptime(release_date, "%Y-%m-%d")
        today = datetime.now()
        expected_days = (today - release).days + 1
        
        gap = expected_days - actual_days
        
        logger.info(f"Expected: {expected_days}, Actual: {actual_days}, Gap: {gap}")
        
        return gap < 2
        
    except Exception as e:
        logger.error(f"Gap check failed: {e}")
        return True


def close_movie_and_calculate_verdict(movie_id: str, movie: Dict):
    """Close movie and calculate verdict"""
    try:
        title = movie.get('title')
        budget = movie.get('budget', 0)
        india_gross = movie.get('india_gross_total', 0)
        
        verdict = 'pending'
        
        if budget > 0 and india_gross > 0:
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
        
        directus_patch(f"/items/movies/{movie_id}", {
            'status': 'closed',
            'verdict': verdict
        })
        
        logger.info(f"✅ Closed: {title} - Verdict: {verdict}")
        
        # Slack notification
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🏁 MOVIE CLOSED"}
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{title}*\nIndia Gross: ₹{india_gross} Cr\nBudget: ₹{budget} Cr\nVerdict: *{verdict.upper()}*"
                }
            }
        ]
        
        slack_post_message(blocks, f"Movie closed: {title}")
        
    except Exception as e:
        logger.error(f"Close movie failed: {e}")

# ============================================================================
# SCRAPER (Every 4 hours)
# ============================================================================

def scrape_all_running_movies():
    """Scrape live data + backfill + retry failed"""
    logger.info("=" * 60)
    logger.info("SCRAPER: LIVE DATA")
    logger.info("=" * 60)
    
    try:
        result = directus_get("/items/movies?filter[status][_eq]=running&limit=1000")
        running_movies = result.get('data', [])
        
        if not running_movies:
            logger.info("No running movies")
            return
        
        logger.info(f"Scraping {len(running_movies)} movies")
        
        for movie in running_movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                sacnilk_url = movie.get('sacnilk_source_url')
                release_date = movie.get('release_date')
                
                if not sacnilk_url:
                    continue
                
                logger.info(f"Scraping: {title}")
                
                html = get_page_content(sacnilk_url)
                if not html:
                    continue
                
                parsed = parse_box_office_table(html)
                if not parsed:
                    continue
                
                # Update daily stats
                today = datetime.now().date().strftime('%Y-%m-%d')
                
                for day_data in parsed['days']:
                    day_number = day_data['day_number']
                    india_net = day_data['india_net']
                    
                    # Check if exists
                    result = directus_get(
                        f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[day_number][_eq]={day_number}&limit=1"
                    )
                    
                    existing = result.get('data', [])
                    
                    if existing:
                        stats = existing[0]
                        day_date = stats.get('date')
                        
                        # Update only today
                        if day_date == today:
                            directus_patch(f"/items/daily_stats/{stats['id']}", {
                                'india_net': india_net,
                                'is_estimate': True
                            })
                            logger.info(f"Updated Day {day_number}: ₹{india_net} Cr")
                    else:
                        # Backfill missing day
                        day_date = (datetime.strptime(release_date, '%Y-%m-%d') + timedelta(days=day_number - 1)).strftime('%Y-%m-%d')
                        
                        stats_payload = {
                            'movie_id': movie_id,
                            'day_number': day_number,
                            'date': day_date,
                            'india_net': india_net,
                            'is_estimate': False,
                            'seo_content': '',
                            'slug': slugify(f"{title}-day-{day_number}-box-office-collection"),
                            'tags': [title, f"day {day_number}"]
                        }
                        
                        result = directus_post('/items/daily_stats', stats_payload)
                        
                        if result.get('data'):
                            # Queue AI job
                            enqueue_job('queue:content_generation', {
                                'type': 'daily_box_office_actual',
                                'movie_id': movie_id,
                                'day_number': day_number,
                                'movie_title': title,
                                'mode': 'actual',
                                'india_net': india_net
                            })
                            
                            logger.info(f"Backfilled Day {day_number}: ₹{india_net} Cr")
                
                # Update movie totals
                if parsed.get('totals'):
                    update_data = {}
                    
                    if 'india_gross_total' in parsed['totals']:
                        update_data['india_gross_total'] = parsed['totals']['india_gross_total']
                    
                    if 'overseas_total' in parsed['totals']:
                        update_data['overseas_total'] = parsed['totals']['overseas_total']
                    
                    if update_data:
                        directus_patch(f"/items/movies/{movie_id}", update_data)
                
                logger.info(f"✅ Scraped: {title}")
                
                time.sleep(random.uniform(3, 7))
                
            except Exception as e:
                logger.error(f"Error scraping {title}: {e}")
                continue
        
        # Retry failed jobs
        failed_jobs = get_failed_jobs()
        if failed_jobs:
            logger.info(f"Retrying {len(failed_jobs)} failed jobs")
            for job in failed_jobs:
                enqueue_job('queue:content_generation', job)
        
        logger.info("Scraper complete")
        
    except Exception as e:
        logger.error(f"Scraper failed: {e}")

# ============================================================================
# AUDITOR (03:00 AM)
# ============================================================================

def run_audit():
    """Correct estimates from past 3 days"""
    logger.info("=" * 60)
    logger.info("AUDITOR: CORRECT ESTIMATES")
    logger.info("=" * 60)
    
    try:
        today = datetime.now().date()
        three_days_ago = (today - timedelta(days=3)).strftime('%Y-%m-%d')
        today_str = today.strftime('%Y-%m-%d')
        
        result = directus_get("/items/movies?filter[status][_eq]=running&limit=1000")
        running_movies = result.get('data', [])
        
        if not running_movies:
            logger.info("No running movies")
            return
        
        logger.info(f"Auditing {len(running_movies)} movies")
        
        for movie in running_movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                sacnilk_url = movie.get('sacnilk_source_url')
                
                # Get estimates from past 3 days (not today)
                result = directus_get(
                    f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[is_estimate][_eq]=true&filter[date][_gte]={three_days_ago}&filter[date][_lt]={today_str}&limit=100"
                )
                
                estimates = result.get('data', [])
                
                if not estimates:
                    continue
                
                logger.info(f"{title}: Correcting {len(estimates)} estimates")
                
                # Scrape current data
                html = get_page_content(sacnilk_url)
                if not html:
                    continue
                
                parsed = parse_box_office_table(html)
                if not parsed:
                    continue
                
                # Create lookup
                actual_data = {day['day_number']: day for day in parsed['days']}
                
                # Correct each estimate
                for estimate in estimates:
                    day_number = estimate['day_number']
                    
                    if day_number in actual_data:
                        new_value = actual_data[day_number]['india_net']
                        old_value = estimate.get('india_net', 0)
                        
                        directus_patch(f"/items/daily_stats/{estimate['id']}", {
                            'india_net': new_value,
                            'is_estimate': False
                        })
                        
                        logger.info(f"Corrected Day {day_number}: ₹{old_value} → ₹{new_value} Cr")
                
                # Update movie totals
                if parsed.get('totals'):
                    update_data = {}
                    
                    if 'india_gross_total' in parsed['totals']:
                        update_data['india_gross_total'] = parsed['totals']['india_gross_total']
                    
                    if 'overseas_total' in parsed['totals']:
                        update_data['overseas_total'] = parsed['totals']['overseas_total']
                    
                    if update_data:
                        directus_patch(f"/items/movies/{movie_id}", update_data)
                
                time.sleep(random.uniform(2, 5))
                
            except Exception as e:
                logger.error(f"Error auditing {title}: {e}")
                continue
        
        logger.info("Audit complete")
        
    except Exception as e:
        logger.error(f"Audit failed: {e}")

# ============================================================================
# RSS MONITOR (Every 5 minutes)
# ============================================================================

def check_rss_feeds():
    """Check all RSS feeds and process entries"""
    logger.info("=" * 60)
    logger.info("RSS MONITOR: CHECK FEEDS")
    logger.info("=" * 60)
    
    try:
        # Get feeds
        news_feeds = get_setting('news_rss_feeds', [])
        box_office_feeds = get_setting('box_office_rss_feeds', [])
        
        all_feeds = news_feeds + box_office_feeds
        
        if not all_feeds:
            logger.info("No RSS feeds configured")
            return
        
        logger.info(f"Checking {len(all_feeds)} feeds")
        
        # Get context for budget LLM
        movies_context = get_active_movies_context()
        people_context = get_all_people_context()
        
        processed_count = 0
        
        for feed_config in all_feeds:
            if not feed_config.get('enabled', True):
                continue
            
            feed_url = feed_config.get('url')
            
            try:
                logger.info(f"Parsing: {feed_url}")
                
                feed = feedparser.parse(feed_url)
                
                for entry in feed.entries:
                    source_url = entry.get('link', '')
                    
                    if not source_url:
                        continue
                    
                    # Check if already processed
                    existing = directus_get(
                        f"/items/news_leads?filter[source_url][_eq]={source_url}&limit=1"
                    )
                    
                    if existing.get('data'):
                        continue
                    
                    # Budget LLM pre-check
                    analysis = budget_llm_precheck(entry, movies_context, people_context)
                    
                    if not analysis or not analysis.get('is_relevant', True):
                        logger.info(f"Skipped (not relevant): {entry.get('title', '')[:50]}")
                        continue
                    
                    # Create news_leads
                    lead_data = {
                        'title': entry.get('title', ''),
                        'source_url': source_url,
                        'status': 'pending'
                    }
                    
                    result = directus_post('/items/news_leads', lead_data)
                    lead_id = result.get('data', {}).get('id')
                    
                    if not lead_id:
                        continue
                    
                    # Post to Slack
                    post_to_slack_for_approval(entry, lead_id, analysis)
                    
                    processed_count += 1
                    time.sleep(1)
                
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Feed error: {e}")
                continue
        
        logger.info(f"RSS check complete: {processed_count} new entries")
        
    except Exception as e:
        logger.error(f"RSS monitor failed: {e}")


def get_active_movies_context() -> str:
    """Get active movies for LLM context"""
    try:
        today = datetime.now().date()
        two_months_ago = (today - timedelta(days=60)).strftime('%Y-%m-%d')
        
        result = directus_get(
            f"/items/movies?filter[release_date][_gte]={two_months_ago}&limit=500&fields=id,title,release_date,status"
        )
        
        movies = result.get('data', [])
        
        movie_list = []
        for m in movies:
            movie_list.append(f"- {m.get('title')} (id: {m.get('id')}, release: {m.get('release_date')})")
        
        return "\n".join(movie_list)
        
    except Exception as e:
        logger.error(f"Get movies context failed: {e}")
        return ""


def get_all_people_context() -> str:
    """Get all people for LLM context"""
    try:
        result = directus_get("/items/people?limit=1000&fields=id,name")
        people = result.get('data', [])
        
        people_list = []
        for p in people:
            people_list.append(f"- {p.get('name')} (id: {p.get('id')})")
        
        return "\n".join(people_list)
        
    except Exception as e:
        logger.error(f"Get people context failed: {e}")
        return ""


def budget_llm_precheck(entry: Dict, movies_context: str, people_context: str) -> Optional[Dict]:
    """Budget LLM for relevance checking"""
    try:
        model = get_setting("budget_model", "openai/gpt-4o-mini")
        
        title = entry.get('title', '')
        description = entry.get('description', '')[:200]
        
        prompt = f"""Analyze this entertainment news headline.

HEADLINE: {title}

SNIPPET: {description}

AVAILABLE MOVIES:
{movies_context[:1000]}

AVAILABLE PEOPLE:
{people_context[:1000]}

Determine:
1. Is this relevant entertainment news?
2. Which movie(s)?
3. Which people?
4. Category: news, review, or ott
5. Confidence (0-1)

Return ONLY JSON:
{{
  "is_relevant": true/false,
  "confidence": 0.95,
  "movie_ids": ["uuid1"],
  "people_ids": ["uuid1"],
  "category_id": "uuid"
}}"""
        
        result = call_openrouter(model, prompt, 0.3, 500)
        
        if result:
            return extract_json_from_text(result)
        
        return None
        
    except Exception as e:
        logger.error(f"Budget LLM failed: {e}")
        return None


def post_to_slack_for_approval(entry: Dict, lead_id: str, analysis: Optional[Dict]):
    """Post RSS entry to Slack with dropdowns"""
    try:
        title = entry.get('title', '')
        source_url = entry.get('link', '')
        
        # Get all movies/people/categories for dropdowns
        movies = directus_get("/items/movies?limit=500&fields=id,title").get('data', [])
        people = directus_get("/items/people?limit=500&fields=id,name").get('data', [])
        categories = directus_get("/items/categories?limit=100&fields=id,name").get('data', [])
        
        # Build options (max 100 per Slack limit)
        movie_options = [{"text": {"type": "plain_text", "text": m['title'][:75]}, "value": m['id']} for m in movies[:100]]
        people_options = [{"text": {"type": "plain_text", "text": p['name'][:75]}, "value": p['id']} for p in people[:100]]
        category_options = [{"text": {"type": "plain_text", "text": c['name']}, "value": c['id']} for c in categories if c.get('name', '').lower() != 'box office']
        
        # Confidence badge
        confidence = analysis.get('confidence', 0) if analysis else 0
        if confidence >= 0.85:
            badge = f"🟢 AI Confidence: {int(confidence * 100)}%"
        elif confidence >= 0.50:
            badge = f"🟡 AI Confidence: {int(confidence * 100)}%"
        else:
            badge = f"🔴 AI Confidence: {int(confidence * 100)}%"
        
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "📰 NEW ARTICLE LEAD"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{badge}*"}
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Headline:*\n{title}\n\n*Source:* {source_url}"}
            },
            {
                "type": "input",
                "block_id": "movies_block",
                "optional": True,
                "element": {
                    "type": "multi_static_select",
                    "action_id": "select_movies",
                    "placeholder": {"type": "plain_text", "text": "Select movies"},
                    "options": movie_options
                },
                "label": {"type": "plain_text", "text": "🎬 Movies"}
            },
            {
                "type": "input",
                "block_id": "people_block",
                "optional": True,
                "element": {
                    "type": "multi_static_select",
                    "action_id": "select_people",
                    "placeholder": {"type": "plain_text", "text": "Select people"},
                    "options": people_options
                },
                "label": {"type": "plain_text", "text": "👥 People"}
            },
            {
                "type": "input",
                "block_id": "category_block",
                "element": {
                    "type": "static_select",
                    "action_id": "select_category",
                    "placeholder": {"type": "plain_text", "text": "Select category"},
                    "options": category_options
                },
                "label": {"type": "plain_text", "text": "📁 Category"}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "value": lead_id,
                        "action_id": "approve_article"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "value": lead_id,
                        "action_id": "reject_article"
                    }
                ]
            }
        ]
        
        slack_post_message(blocks, f"New article: {title}")
        
    except Exception as e:
        logger.error(f"Slack post failed: {e}")

# ============================================================================
# MASTER SCHEDULER
# ============================================================================

def run_publishing_pipeline():
    """00:05 AM: Discovery + Transition + Daily Pages"""
    try:
        logger.info("🚀 STARTING PUBLISHING PIPELINE")
        discover_new_movies()
        update_announced_movies()
        transition_movies_to_running()
        create_daily_pages()
        logger.info("✅ PUBLISHING PIPELINE COMPLETE")
    except Exception as e:
        logger.error(f"Publishing pipeline failed: {e}")


if __name__ == "__main__":
    # Schedule all tasks
    schedule.every().day.at("00:05").do(run_publishing_pipeline)
    schedule.every().day.at("03:00").do(run_audit)
    schedule.every(4).hours.do(scrape_all_running_movies)
    schedule.every(5).minutes.do(check_rss_feeds)
    
    # Run scraper immediately on startup
    logger.info("Running scraper immediately on startup...")
    scrape_all_running_movies()
    
    # Keep running
    logger.info("Scheduler started")
    logger.info("Schedule:")
    logger.info("  - 00:05: Publishing Pipeline (Discovery + Transition + Daily)")
    logger.info("  - 03:00: Audit (Correct estimates)")
    logger.info("  - Every 4h: Scraper (Live data + backfill)")
    logger.info("  - Every 5m: RSS Monitor")
    
    while True:
        schedule.run_pending()
        time.sleep(60)