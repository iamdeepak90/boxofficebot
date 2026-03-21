"""
movie_discovery.py - Discover movies from Sacnilk + Daily metadata updates
Runs: Daily at 12:05 AM IST
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import *
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import time
import random
import schedule
import time as time_module


# ============================================================================
# SACNILK SCRAPING
# ============================================================================

def scrape_sacnilk_upcoming() -> List[Dict]:
    """
    Scrape Sacnilk Upcoming Movies page
    Returns: List of movie data
    """
    try:
        url = "https://sacnilk.com/entertainmenttopbar/Upcoming_Movies"
        logger.info(f"Scraping Sacnilk Upcoming: {url}")
        
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find movie links/cards
        # NOTE: Adjust selectors based on actual Sacnilk HTML structure
        movies = []
        
        # Example structure (adjust based on actual HTML):
        movie_cards = soup.find_all('div', class_='movie-card')  # Placeholder selector
        
        for card in movie_cards:
            try:
                # Extract basic data
                title_elem = card.find('h3', class_='movie-title')  # Adjust
                link_elem = card.find('a', href=True)
                
                if not title_elem or not link_elem:
                    continue
                
                title = title_elem.text.strip()
                sacnilk_url = link_elem['href']
                
                # Make absolute URL
                if not sacnilk_url.startswith('http'):
                    sacnilk_url = f"https://sacnilk.com{sacnilk_url}"
                
                movies.append({
                    'title': title,
                    'sacnilk_source_url': sacnilk_url
                })
                
            except Exception as e:
                logger.warning(f"Error parsing movie card: {e}")
                continue
        
        logger.info(f"Found {len(movies)} upcoming movies")
        return movies
        
    except Exception as e:
        logger.error(f"Failed to scrape Sacnilk upcoming: {e}")
        return []


def scrape_movie_details(sacnilk_url: str) -> Optional[Dict]:
    """
    Scrape full movie details from Sacnilk movie page
    Returns: Dict with all movie data or None
    """
    try:
        logger.info(f"Scraping movie details: {sacnilk_url}")
        
        response = requests.get(sacnilk_url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract all available data
        # NOTE: Adjust selectors based on actual HTML structure
        
        data = {
            'title': None,
            'release_date': None,
            'language': [],
            'genre': [],
            'poster_url': None,
            'cast_names': [],
            'budget': None,
            'plot': None
        }
        
        # Title
        title_elem = soup.find('h1', class_='movie-title')  # Adjust
        if title_elem:
            data['title'] = title_elem.text.strip()
        
        # Release date
        release_elem = soup.find('span', class_='release-date')  # Adjust
        if release_elem:
            # Parse date (format might vary)
            date_text = release_elem.text.strip()
            try:
                # Try common formats
                for fmt in ['%d %B %Y', '%Y-%m-%d', '%d-%m-%Y']:
                    try:
                        parsed = datetime.strptime(date_text, fmt)
                        data['release_date'] = parsed.strftime('%Y-%m-%d')
                        break
                    except:
                        continue
            except:
                logger.warning(f"Could not parse date: {date_text}")
        
        # Languages
        lang_elem = soup.find('span', class_='language')  # Adjust
        if lang_elem:
            langs = lang_elem.text.strip()
            data['language'] = [l.strip() for l in langs.split(',')]
        
        # Genre
        genre_elem = soup.find('span', class_='genre')  # Adjust
        if genre_elem:
            genres = genre_elem.text.strip()
            data['genre'] = [g.strip() for g in genres.split(',')]
        
        # Poster
        poster_elem = soup.find('img', class_='movie-poster')  # Adjust
        if poster_elem and poster_elem.get('src'):
            poster_url = poster_elem['src']
            if not poster_url.startswith('http'):
                poster_url = f"https://sacnilk.com{poster_url}"
            data['poster_url'] = poster_url
        
        # Cast & Crew
        cast_section = soup.find('div', class_='cast-section')  # Adjust
        if cast_section:
            cast_names = []
            for person in cast_section.find_all('span', class_='person-name'):
                cast_names.append(person.text.strip())
            data['cast_names'] = cast_names
        
        # Budget
        budget_elem = soup.find('span', class_='budget')  # Adjust
        if budget_elem:
            budget_text = budget_elem.text.strip()
            data['budget'] = parse_number_from_text(budget_text)
        
        # Plot
        plot_elem = soup.find('div', class_='plot')  # Adjust
        if plot_elem:
            data['plot'] = plot_elem.text.strip()
        
        return data
        
    except Exception as e:
        logger.error(f"Failed to scrape movie details: {e}")
        return None


# ============================================================================
# PEOPLE MANAGEMENT
# ============================================================================

def get_or_create_person(name: str, person_type: str = "actor") -> Optional[str]:
    """
    Get existing person or create new one
    Returns: person UUID or None
    """
    try:
        # Check if exists
        result = directus_get(
            f"/items/people?filter[name][_eq]={name}&limit=1"
        )
        
        if result.get('data') and len(result['data']) > 0:
            person_id = result['data'][0]['id']
            logger.info(f"Person exists: {name} ({person_id})")
            return person_id
        
        # Create new person
        logger.info(f"Creating new person: {name}")
        
        person_data = {
            'name': name,
            'slug': slugify(name),
            'type': [person_type],  # JSON array
            'status': 'published'
        }
        
        result = directus_post('/items/people', person_data)
        person_id = result.get('data', {}).get('id')
        
        logger.info(f"Person created: {name} ({person_id})")
        return person_id
        
    except Exception as e:
        logger.error(f"Error with person {name}: {e}")
        return None


def process_cast_crew(cast_names: List[str]) -> List[str]:
    """
    Process cast names and return list of people UUIDs
    """
    people_ids = []
    
    for name in cast_names:
        if not name:
            continue
        
        person_id = get_or_create_person(name, "actor")
        if person_id:
            people_ids.append(person_id)
    
    return people_ids


# ============================================================================
# AI PLOT HUMANIZATION
# ============================================================================

def humanize_plot(raw_plot: str, movie_title: str) -> str:
    """
    Use AI to humanize and rewrite plot (2 stages: Gen → Humanize, NO SEO)
    Returns: humanized plot or original if fails
    """
    try:
        if not raw_plot:
            return ""
        
        # STAGE 1: Generation
        model = get_setting("plot_generation_model", "anthropic/claude-3.5-sonnet")
        temperature = get_setting("plot_generation_temperature", 0.7)
        max_tokens = get_setting("plot_generation_max_tokens", 2000)
        
        prompt = f"""Rewrite this movie plot in 2-3 engaging paragraphs for SEO.

Movie: {movie_title}

Raw Plot:
{raw_plot}

Requirements:
- Make it engaging and natural
- Use clear, concise language
- Avoid spoilers
- 150-200 words
- No AI phrases like "it's worth noting"

Return only the rewritten plot, no extra text."""
        
        draft = call_openrouter(model, prompt, temperature, max_tokens)
        
        if not draft:
            logger.warning("Plot generation failed, using original")
            return raw_plot
        
        # STAGE 2: Humanization
        humanize_model = get_setting("plot_humanize_model", "anthropic/claude-3.5-sonnet")
        humanize_temp = get_setting("plot_humanize_temperature", 0.8)
        humanize_tokens = get_setting("plot_humanize_max_tokens", 2000)
        
        humanize_prompt = f"""Make this plot description more natural and human-sounding.

DRAFT:
{draft}

Requirements:
- Remove any AI-like phrases
- Make it conversational yet professional
- Keep it concise (150-200 words)

Return only the humanized plot."""
        
        humanized = call_openrouter(humanize_model, humanize_prompt, humanize_temp, humanize_tokens)
        
        if humanized:
            logger.info("Plot humanized successfully (2 stages)")
            return humanized.strip()
        else:
            logger.warning("Humanization failed, using draft")
            return draft.strip()


# ============================================================================
# FUZZY DEDUPLICATION
# ============================================================================

def check_duplicate_movie(title: str, sacnilk_url: str) -> Optional[Dict]:
    """
    Check if movie already exists (exact URL or fuzzy title match)
    Returns: existing movie data if found, None otherwise
    """
    try:
        # Check by exact URL first
        result = directus_get(
            f"/items/movies?filter[sacnilk_source_url][_eq]={sacnilk_url}&limit=1"
        )
        
        if result.get('data') and len(result['data']) > 0:
            logger.info(f"Movie exists (URL match): {title}")
            return result['data'][0]
        
        # Check by fuzzy title match
        threshold = get_setting("fuzzy_match_threshold", 90)
        
        # Get all movies
        all_movies = directus_get("/items/movies?limit=1000")
        
        for movie in all_movies.get('data', []):
            existing_title = movie.get('title', '')
            if fuzzy_match(title, existing_title, threshold):
                logger.warning(f"Possible duplicate found: {title} ~ {existing_title}")
                return {
                    'is_fuzzy_match': True,
                    'existing_movie': movie,
                    'similarity': fuzz.ratio(title.lower(), existing_title.lower())
                }
        
        return None
        
    except Exception as e:
        logger.error(f"Duplicate check error: {e}")
        return None


def send_duplicate_alert_slack(new_title: str, existing_title: str, similarity: int, new_url: str):
    """Send Slack alert for manual duplicate review"""
    try:
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🔔 POSSIBLE DUPLICATE MOVIE"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Found on Sacnilk:*\n{new_title}\n\n*Existing in Database:*\n{existing_title}\n\n*Similarity:* {similarity}%"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Sacnilk URL:*\n{new_url}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Create New"},
                        "value": f"create_new|{new_url}",
                        "action_id": "duplicate_create_new"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Skip"},
                        "value": f"skip|{new_url}",
                        "action_id": "duplicate_skip"
                    }
                ]
            }
        ]
        
        slack_post_message(blocks, f"Duplicate check: {new_title}")
        logger.info(f"Duplicate alert sent to Slack")
        
    except Exception as e:
        logger.error(f"Failed to send duplicate alert: {e}")


# ============================================================================
# MOVIE CREATION
# ============================================================================

def create_movie(movie_data: Dict) -> Optional[str]:
    """
    Create new movie in Directus
    Returns: movie UUID or None
    """
    try:
        logger.info(f"Creating movie: {movie_data.get('title')}")
        
        # Process poster
        poster_uuid = None
        if movie_data.get('poster_url'):
            poster_uuid = upload_file_to_directus(
                file_url=movie_data['poster_url'],
                title=f"{movie_data.get('title', 'poster')}.jpg"
            )
        
        # Process cast/crew
        cast_crew_ids = []
        if movie_data.get('cast_names'):
            cast_crew_ids = process_cast_crew(movie_data['cast_names'])
        
        # Humanize plot
        plot = ""
        if movie_data.get('plot'):
            plot = humanize_plot(movie_data['plot'], movie_data.get('title', ''))
        
        # Generate tags
        tags = [movie_data.get('title', '')]
        if movie_data.get('language'):
            tags.extend(movie_data['language'])
        if movie_data.get('genre'):
            tags.extend(movie_data['genre'])
        if movie_data.get('release_date'):
            year = movie_data['release_date'].split('-')[0]
            tags.append(year)
        
        # Create movie entry
        movie_payload = {
            'status': 'announced',
            'title': movie_data.get('title'),
            'slug': slugify(movie_data.get('title', '')),
            'release_date': movie_data.get('release_date'),
            'language': movie_data.get('language', []),
            'genre': movie_data.get('genre', []),
            'sacnilk_source_url': movie_data.get('sacnilk_source_url'),
            'budget': movie_data.get('budget'),
            'plot': plot,
            'tags': tags
        }
        
        # Add optional fields only if they exist
        if poster_uuid:
            movie_payload['poster'] = poster_uuid
        
        if cast_crew_ids:
            movie_payload['cast_crew'] = cast_crew_ids
        
        result = directus_post('/items/movies', movie_payload)
        movie_id = result.get('data', {}).get('id')
        
        logger.info(f"Movie created successfully: {movie_id}")
        return movie_id
        
    except Exception as e:
        logger.error(f"Movie creation failed: {e}")
        logger.error(f"Data: {json.dumps(movie_data, indent=2)}")
        return None


# ============================================================================
# MOVIE UPDATE (MERGE CAST/CREW)
# ============================================================================

def update_movie_metadata(movie_id: str, scraped_data: Dict) -> bool:
    """
    Update movie metadata with merge logic for cast/crew
    Returns: True if successful
    """
    try:
        logger.info(f"Updating movie metadata: {movie_id}")
        
        # Get existing movie
        result = directus_get(f"/items/movies/{movie_id}")
        existing_movie = result.get('data', {})
        
        # Build update payload
        update_payload = {}
        
        # Update simple fields if changed
        for field in ['title', 'release_date', 'budget']:
            if scraped_data.get(field) and scraped_data[field] != existing_movie.get(field):
                update_payload[field] = scraped_data[field]
        
        # Update arrays (language, genre)
        for field in ['language', 'genre']:
            if scraped_data.get(field):
                update_payload[field] = scraped_data[field]
        
        # MERGE cast/crew (additive)
        if scraped_data.get('cast_names'):
            existing_cast_ids = existing_movie.get('cast_crew', [])
            new_cast_ids = process_cast_crew(scraped_data['cast_names'])
            
            # Merge (remove duplicates)
            merged_cast_ids = list(set(existing_cast_ids + new_cast_ids))
            
            if len(merged_cast_ids) > len(existing_cast_ids):
                update_payload['cast_crew'] = merged_cast_ids
                logger.info(f"Cast updated: {len(existing_cast_ids)} → {len(merged_cast_ids)}")
        
        # Update poster if changed
        if scraped_data.get('poster_url'):
            new_poster_uuid = upload_file_to_directus(
                file_url=scraped_data['poster_url'],
                title=f"{scraped_data.get('title', 'poster')}.jpg"
            )
            if new_poster_uuid:
                update_payload['poster'] = new_poster_uuid
        
        # Regenerate plot if changed
        if scraped_data.get('plot') and scraped_data['plot'] != existing_movie.get('plot'):
            new_plot = humanize_plot(scraped_data['plot'], scraped_data.get('title', ''))
            update_payload['plot'] = new_plot
        
        # Regenerate tags
        tags = [scraped_data.get('title', existing_movie.get('title', ''))]
        if scraped_data.get('language'):
            tags.extend(scraped_data['language'])
        if scraped_data.get('genre'):
            tags.extend(scraped_data['genre'])
        update_payload['tags'] = tags
        
        # Update if there are changes
        if update_payload:
            directus_patch(f"/items/movies/{movie_id}", update_payload)
            logger.info(f"Movie updated: {len(update_payload)} fields")
            return True
        else:
            logger.info("No changes to update")
            return True
            
    except Exception as e:
        logger.error(f"Movie update failed: {e}")
        return False


# ============================================================================
# SLACK NOTIFICATIONS
# ============================================================================

def send_new_movie_notification(movie_data: Dict, movie_id: str):
    """Send Slack notification for new movie"""
    try:
        directus_link = f"{directus_url()}/admin/content/movies/{movie_id}"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🎬 NEW MOVIE DISCOVERED"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Title:* {movie_data.get('title')}\n*Release:* {movie_data.get('release_date')}\n*Languages:* {', '.join(movie_data.get('language', []))}\n*Genre:* {', '.join(movie_data.get('genre', []))}"
                }
            }
        ]
        
        if movie_data.get('budget'):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Budget:* ₹{movie_data['budget']} Cr"
                }
            })
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<{movie_data.get('sacnilk_source_url')}|Sacnilk> | <{directus_link}|Directus>"
            }
        })
        
        slack_post_message(blocks, f"New movie: {movie_data.get('title')}")
        
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")


# ============================================================================
# MAIN DISCOVERY WORKFLOW
# ============================================================================

def discover_new_movies():
    """Discover and create new movies from Sacnilk"""
    logger.info("=" * 60)
    logger.info("STARTING MOVIE DISCOVERY")
    logger.info("=" * 60)
    
    try:
        # Scrape upcoming movies list
        upcoming_movies = scrape_sacnilk_upcoming()
        
        if not upcoming_movies:
            logger.warning("No movies found on Sacnilk")
            return
        
        new_count = 0
        
        for movie_basic in upcoming_movies:
            try:
                title = movie_basic.get('title')
                sacnilk_url = movie_basic.get('sacnilk_source_url')
                
                logger.info(f"\nProcessing: {title}")
                
                # Check for duplicates
                duplicate = check_duplicate_movie(title, sacnilk_url)
                
                if duplicate:
                    if duplicate.get('is_fuzzy_match'):
                        # Fuzzy match - send to Slack for manual review
                        send_duplicate_alert_slack(
                            title,
                            duplicate['existing_movie']['title'],
                            duplicate['similarity'],
                            sacnilk_url
                        )
                        logger.info("Fuzzy duplicate - sent to Slack for review")
                        continue
                    else:
                        # Exact URL match - skip
                        logger.info("Movie already exists (URL match) - skipping")
                        continue
                
                # Scrape full details
                movie_data = scrape_movie_details(sacnilk_url)
                
                if not movie_data:
                    logger.warning(f"Could not scrape details for {title}")
                    continue
                
                # Add sacnilk URL to data
                movie_data['sacnilk_source_url'] = sacnilk_url
                
                # Create movie
                movie_id = create_movie(movie_data)
                
                if movie_id:
                    new_count += 1
                    send_new_movie_notification(movie_data, movie_id)
                
                # Rate limiting
                time.sleep(random.uniform(2, 4))
                
            except Exception as e:
                logger.error(f"Error processing movie {title}: {e}")
                continue
        
        logger.info(f"\nDiscovery complete: {new_count} new movies created")
        
    except Exception as e:
        logger.error(f"Discovery workflow failed: {e}")
    
    logger.info("=" * 60)


def update_announced_movies():
    """Update metadata for announced movies (until Day 3)"""
    logger.info("=" * 60)
    logger.info("UPDATING ANNOUNCED MOVIES METADATA")
    logger.info("=" * 60)
    
    try:
        # Get announced movies
        result = directus_get("/items/movies?filter[status][_eq]=announced&limit=1000")
        announced_movies = result.get('data', [])
        
        logger.info(f"Found {len(announced_movies)} announced movies")
        
        updated_count = 0
        
        for movie in announced_movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                sacnilk_url = movie.get('sacnilk_source_url')
                
                logger.info(f"\nUpdating: {title}")
                
                # Scrape latest data
                scraped_data = scrape_movie_details(sacnilk_url)
                
                if not scraped_data:
                    logger.warning(f"Could not scrape details for {title}")
                    continue
                
                # Update movie
                if update_movie_metadata(movie_id, scraped_data):
                    updated_count += 1
                
                # Rate limiting
                time.sleep(random.uniform(2, 4))
                
            except Exception as e:
                logger.error(f"Error updating movie {title}: {e}")
                continue
        
        logger.info(f"\nUpdate complete: {updated_count} movies updated")
        
    except Exception as e:
        logger.error(f"Update workflow failed: {e}")
    
    logger.info("=" * 60)


def stop_updating_old_running_movies():
    """
    Stop updating movies that are Day 3+
    (Metadata updates stop after Day 3)
    """
    logger.info("Checking for movies to stop updating...")
    
    try:
        today = datetime.now().date()
        cutoff_date = (today - timedelta(days=3)).strftime('%Y-%m-%d')
        
        # Get running movies older than Day 3
        result = directus_get(
            f"/items/movies?filter[status][_eq]=running&filter[release_date][_lt]={cutoff_date}&limit=1000"
        )
        
        old_movies = result.get('data', [])
        logger.info(f"Found {len(old_movies)} movies past Day 3 (no metadata updates)")
        
        # Note: No action needed - just log for reference
        # Phase 1 Part C already skips these in update logic
        
    except Exception as e:
        logger.error(f"Stop update check failed: {e}")


# ============================================================================
# SCHEDULER FOR COOLIFY
# ============================================================================

def run_discovery_job():
    """Wrapper for scheduled execution"""
    try:
        logger.info("Scheduled discovery job triggered")
        discover_new_movies()
        update_announced_movies()
        stop_updating_old_running_movies()
    except Exception as e:
        logger.error(f"Scheduled job failed: {e}")


if __name__ == "__main__":
    # Schedule daily at 12:05 AM IST
    schedule.every().day.at("00:05").do(run_discovery_job)
    
    # Keep script running
    logger.info("Discovery scheduler started. Running daily at 00:05 IST")
    logger.info("Press Ctrl+C to stop")
    
    while True:
        schedule.run_pending()
        time_module.sleep(60)