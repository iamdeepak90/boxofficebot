"""
scheduler.py - All scheduled automation tasks Runs:
- 00:05 AM: Discovery + Transition + Daily Pages
- 03:00 AM: Audit estimates
- Every 4 hours: Scraper
- Every 5 minutes: RSS feeds
"""

import sys
import os
from common import *
from datetime import datetime, timedelta
from typing import Optional
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
        movies = scrape_sacnilk_movies('https://sacnilk.com/entertainmenttopbar/Upcoming_Movies')
        
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
                    # Now that we have release_date, build proper slug with year
                    release_year = str(movie_data.get('release_date', ''))[:4]
                    if release_year.isdigit():
                        movie_data['slug'] = f"{slugify(title)}-{release_year}"
                
                # Process cast & crew
                cast_ids = []
                for person_data in movie_data.get('cast_and_crew', []):
                    person_id = get_or_create_person(
                        name=person_data.get('name', '').strip(),
                        types=person_data.get('types', []),
                        sacnilk_url=person_data.get('sacnilk_url')
                    )
                    if person_id and person_id not in cast_ids:
                        cast_ids.append(person_id)
                
                # Humanize summary (2 stages: Gen → Humanize)
                raw_summary = movie_data.get('summary', '')
                if raw_summary:
                    humanized_plot = humanize_plot(raw_summary, title)
                    movie_data['plot'] = humanized_plot
                
                # Upload poster
                poster_uuid = None
                poster_url = movie_data.get('poster')  # scrape_movie_details returns key 'poster', not 'poster_url'
                if poster_url and poster_url.startswith('http'):
                    poster_uuid = upload_file_to_directus(file_url=poster_url, title=slugify(title))
                    if not poster_uuid:
                        logger.warning(f"Poster unavailable for '{title}', creating without poster")
                
                # Create movie
                ott_platform = movie_data.get('ott_platform')
                if isinstance(ott_platform, list):
                    ott_platform = ', '.join(ott_platform) if ott_platform else None

                create_data = {
                    'status': 'announced',
                    'title': title,
                    'slug': movie_data.get('slug'),
                    'release_date': movie_data.get('release_date'),
                    'language': movie_data.get('languages') or None,
                    'genre': movie_data.get('genre') or None,
                    'sacnilk_source_url': sacnilk_url,
                    'poster': poster_uuid,
                    'budget': movie_data.get('budget') or None,
                    'plot': movie_data.get('plot') or None,
                    'runtime': movie_data.get('runtime') or None,
                    'cbfc_rating': movie_data.get('cbfc_rating') or None,
                    'ott_platform': ott_platform,
                    'ott_release_date': movie_data.get('ott_release_date') or None,
                    'cast_crew': [{'people_id': pid} for pid in cast_ids],
                    'tags': movie_data.get('tags') or []
                }
                
                result = directus_post('/items/movies', create_data)

                if not result or not result.get('data'):
                    logger.error(f"Failed to create movie in Directus: {title}")
                    continue

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



def update_announced_movies():
    """Smart metadata updates based on movie age"""
    logger.info("=" * 60)
    logger.info("UPDATE: MOVIE METADATA")
    logger.info("=" * 60)
    
    try:
        today = datetime.now().date()
        
        # Calculate date ranges
        two_months_ago = (today - timedelta(days=60)).strftime('%Y-%m-%d')
        four_months_ago = (today - timedelta(days=120)).strftime('%Y-%m-%d')
        six_months_ago = (today - timedelta(days=180)).strftime('%Y-%m-%d')
        
        # Determine what to update based on day of week
        day_of_week = today.weekday()  # 0=Monday, 6=Sunday
        
        movies_to_update = []
        
        # DAILY: Announced + Released within 2 months
        result = directus_get(
            f"/items/movies?filter[_or][0][status][_eq]=announced&filter[_or][1][_and][0][status][_in]=running,closed&filter[_or][1][_and][1][release_date][_gte]={two_months_ago}&limit=1000"
        )
        movies_to_update.extend(result.get('data', []))
        logger.info(f"Daily updates: {len(movies_to_update)} movies (announced + released <2 months)")
        
        # WEEKLY (Sundays): 2-4 months old
        if day_of_week == 6:  # Sunday
            result = directus_get(
                f"/items/movies?filter[status][_in]=running,closed&filter[release_date][_gte]={four_months_ago}&filter[release_date][_lt]={two_months_ago}&limit=1000"
            )
            weekly = result.get('data', [])
            movies_to_update.extend(weekly)
            logger.info(f"Weekly updates: {len(weekly)} movies (2-4 months old)")
        
        # BI-WEEKLY (1st & 15th): 4-6 months old
        if today.day in [1, 15]:
            result = directus_get(
                f"/items/movies?filter[status][_in]=running,closed&filter[release_date][_gte]={six_months_ago}&filter[release_date][_lt]={four_months_ago}&limit=1000"
            )
            biweekly = result.get('data', [])
            movies_to_update.extend(biweekly)
            logger.info(f"Bi-weekly updates: {len(biweekly)} movies (4-6 months old)")
        
        # Update each movie
        update_count = 0
        for movie in movies_to_update:
            try:
                title = movie.get('title')
                sacnilk_url = movie.get('sacnilk_source_url')
                
                if not sacnilk_url:
                    continue
                
                logger.info(f"Updating: {title}")
                
                # Scrape fresh details
                details = scrape_movie_details(sacnilk_url)
                if not details:
                    continue
                
                # Merge cast
                existing_cast_raw = movie.get('cast_crew', [])
                existing_cast_ids = []

                for item in existing_cast_raw:
                    if isinstance(item, dict):
                        pid = item.get('people_id')

                        # Expanded relation case: {'people_id': {'id': 78, ...}}
                        if isinstance(pid, dict):
                            pid = pid.get('id')

                        # Direct relation object case: {'id': 123, 'people_id': 78}
                        if not pid and item.get('id') and item.get('people_id'):
                            pid = item.get('people_id')

                        if pid:
                            existing_cast_ids.append(pid)

                    elif item:
                        existing_cast_ids.append(item)

                for person_data in details.get('cast_and_crew', []):
                    person_id = get_or_create_person(
                        name=person_data.get('name', '').strip(),
                        types=person_data.get('types', []),
                        sacnilk_url=person_data.get('sacnilk_url')
                    )
                    if person_id and person_id not in existing_cast_ids:
                        existing_cast_ids.append(person_id)

                existing_cast_ids = list(dict.fromkeys(existing_cast_ids))

                # Update Poster only if existing movie does not already have poster
                existing_poster = movie.get('poster')
                if not existing_poster:
                    poster_url = details.get('poster')
                    if poster_url:
                        poster_uuid = upload_file_to_directus(file_url=poster_url, title=slugify(title))
                        if poster_uuid:
                            details['poster'] = poster_uuid

                # Update movie
                update_data = {
                    'title': details.get('title', movie.get('title', '')),
                    'language': details.get('languages', movie.get('language', '')),
                    'genre': details.get('genre', movie.get('genre', '')),
                    'release_date': details.get('release_date', movie.get('release_date')),
                    'budget': details.get('budget', movie.get('budget')),
                    'runtime': details.get('runtime', movie.get('runtime')),
                    'cbfc_rating': details.get('cbfc_rating', movie.get('cbfc_rating')),
                    'ott_platform': details.get('ott_platform', movie.get('ott_platform')),
                    'ott_release_date': details.get('ott_release_date', movie.get('ott_release_date')),
                    'india_gross_total': details.get('india_gross_total', movie.get('india_gross_total')),
                    'overseas_total': details.get('overseas_total', movie.get('overseas_total')),
                    'tags': details.get('tags', movie.get('tags', [])),
                    'cast_crew': [{'people_id': pid} for pid in existing_cast_ids],
                    **({'poster': details['poster']} if details.get('poster') else {})
                }
                
                directus_patch(f"/items/movies/{movie['id']}", update_data)
                
                logger.info(f"✅ Updated: {title}")
                update_count += 1
                
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                logger.error(f"Error updating {title}: {e}")
                continue
        
        logger.info(f"Metadata update complete: {update_count} movies updated")
        
    except Exception as e:
        logger.error(f"Update movies failed: {e}")


def humanize_plot(raw_plot: str, movie_title: str) -> str:
    """
    Rewrite a scraped plot into a clean, human-readable short synopsis,
    or generate one if raw_plot is missing.
    """
    try:
        logger.info(f"Humanizing plot for: {movie_title}")

        model = get_setting("plot_humanize_model", "deepseek/deepseek-v3.2")
        temperature = get_setting("plot_humanize_temperature", 0.8)
        max_tokens = get_setting("plot_humanize_max_tokens", 2000)

        raw_plot = (raw_plot or "").strip()
        movie_title = (movie_title or "").strip()

        if raw_plot:
            prompt = f"""You are a professional entertainment writer.

Rewrite the following movie plot into a clean, engaging, human-readable synopsis for "{movie_title}".

STRICT RULES:
- Output plain text only
- No HTML
- No markdown
- No title
- No labels
- No bullet points
- Total length must be exactly 60-80 words
- Use only 1 or 2 short paragraphs
- Keep the meaning faithful to the source
- Remove scraped noise, repetition, awkward phrasing, and spoilers where possible
- Make it natural and editorially polished

SOURCE PLOT:
{raw_plot}

Return only the final rewritten plot."""
        else:
            prompt = f"""You are a professional entertainment writer.

Write a short, clean, engaging movie plot synopsis for "{movie_title}".

STRICT RULES:
- Output plain text only
- No HTML
- No markdown
- No title
- No labels
- No bullet points
- Total length must be exactly 60-80 words
- Use only 1 or 2 short paragraphs
- Keep it general and spoiler-light
- Sound natural, polished, and editorial

Return only the final plot."""
        
        result = call_openrouter(model, prompt, temperature, max_tokens)

        if not result:
            logger.warning("Plot humanization/generation failed")
            return raw_plot[:400].strip() if raw_plot else ""

        result = result.strip()

        # Basic cleanup to enforce plain text only
        result = result.replace("```", "").replace("<p>", "").replace("</p>", "").strip()

        return result

    except Exception as e:
        logger.error(f"Plot humanization failed for '{movie_title}': {e}")
        return raw_plot[:400].strip() if raw_plot else ""


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

# ============================================================================
# TRANSITION (00:05 AM)
# ============================================================================

def transition_movies_to_running():
    """Transition announced → running on RELEASE DAY (hub only, no day pages)"""
    logger.info("=" * 60)
    logger.info("TRANSITION: ANNOUNCED → RUNNING")
    logger.info("=" * 60)
    
    try:
        today = datetime.now().date().strftime('%Y-%m-%d')
        
        # Get movies releasing TODAY ONLY
        result = directus_get(
            f"/items/movies?filter[status][_eq]=announced&filter[release_date][_eq]={today}&limit=100"
        )
        
        movies = result.get('data', [])
        
        if not movies:
            logger.info("No movies to transition today")
            return
        
        logger.info(f"Transitioning {len(movies)} movies")
        
        for movie in movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                
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
                
                logger.info(f"✅ Transitioned: {title} (hub created, day pages will be created by create_daily_pages())")
                
                # Slack notification
                blocks = [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "🚀 MOVIE RELEASED"}
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{title}*\nStatus: Running\nHub page created"
                        }
                    }
                ]
                
                slack_post_message(blocks, f"Movie released: {title}")
                
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
        
        # Get cast names — handle M2M format [{'people_id': 'uuid'}, ...]
        cast_names = []
        for item in (movie.get('cast_crew', []) or [])[:5]:
            if isinstance(item, dict):
                person_id = item.get('people_id')
                if isinstance(person_id, dict):  # nested: {'people_id': {'id': ...}}
                    person_id = person_id.get('id')
            else:
                person_id = item
            if not person_id:
                continue
            result = directus_get(f"/items/people/{person_id}?fields=name")
            person = result.get('data', {})
            if person:
                cast_names.append(person.get('name', ''))
        
        cast_text = ', '.join(cast_names) if cast_names else "Star cast"
        
        # Stage 1: Generation
        prompt = f"""You are a senior entertainment journalist writing for a film trade publication.

        MOVIE: {title} | Released: {release_date} | Languages: {languages} | Genre: {genres}
        BUDGET: ₹{budget} Cr
        CAST: {cast_text}
        PLOT: {plot}

        Write an 800-1000 word box office hub page for '{title}' in HTML. This is the central SEO landing page for the film's entire theatrical run.

        IMPORTANT:
        - Keep the section structure fixed, but make the writing fully specific to this film
        - Every section must reflect this movie's unique genre, cast, language market, plot setup, and release context
        - Do not use generic filler that could apply to any movie
        - Do not repeat the same sentence patterns commonly used in entertainment SEO copy
        - Do not invent box office figures, milestones, or verdicts unless explicitly provided
        - No raw data tables, since day-wise figures are shown separately on the page

        STRUCTURE:
        <h2>About {title}</h2>
        Write 2-3 short paragraphs introducing the film, what kind of movie it is, who is involved, and what makes it notable in its release context. Use the plot, genre, language, and cast naturally.

        <h2>{title} Box Office Performance</h2>
        Write 2-3 short paragraphs framing the film's theatrical journey, audience appeal, market positioning, and the main factors likely to influence its run. Keep it specific to this title.

        <h2>Cast & Crew</h2>
        Write 1-2 paragraphs in engaging prose about the principal cast and key creators. Mention why these names matter for this film specifically. Do not write as a list.

        <h2>Budget & Recovery</h2>
        Write 1-2 paragraphs explaining the budget context, recovery discussion, and what the film would need commercially to be seen as average, successful, or underperforming by trade standards. Keep it grounded in this movie's scale and positioning.

        <h2>Frequently Asked Questions</h2>
        Write exactly 5 FAQs in this exact format:
        <p><strong>Q: question</strong></p>
        <p>answer</p>

        Cover:
        - release date
        - languages
        - budget
        - cast
        - box office verdict

        AVOID:
        "It's worth noting", "Delve into", "Remarkable", "Testament to", "Needless to say", "Highly anticipated"
        Also avoid generic openings like:
        - "The film has attracted attention..."
        - "Much will depend on word of mouth..."
        - "The movie is expected to..."

        HTML only — no <html>/<body> wrappers, no inline styles, no markdown fences."""
        
        draft = stage_generation(prompt, 'hub')
        if not draft:
            raise Exception("Generation failed")
        
        # Stage 2: Humanization
        humanized = stage_humanize(draft, 'hub')
        if not humanized:
            humanized = draft
        
        # Stage 3: SEO
        seo_data = stage_seo(humanized, f"{title} Box Office Collection", 'hub')
        
        return {
            "main_content": humanized,
            "meta_title": seo_data.get('meta_title', f"{title} Box Office Collection Day Wise") if seo_data else f"{title} Box Office Collection Day Wise",
            "meta_description": seo_data.get('meta_description', f"Track {title} box office collection day wise.") if seo_data else f"Track {title} box office collection day wise.",
            "tags": seo_data.get('tags', [title, 'box office collection']) if seo_data else [title, 'box office collection']
        }
        
    except Exception as e:
        logger.error(f"Hub generation failed: {e}")
        return {
            "main_content": f"<h1>{movie.get('title')} Box Office Collection</h1>",
            "meta_title": f"{movie.get('title')} Box Office",
            "meta_description": ""
        }


def discover_recent_movies():
    """Scrape recent movies (last 7 days) and auto-create missing data"""
    logger.info("=" * 60)
    logger.info("DISCOVERY: RECENT MOVIES (LAST 7 DAYS)")
    logger.info("=" * 60)
    
    try:
        # Calculate 7 days ago
        today = datetime.now().date()
        seven_days_ago = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Scrape recent movies page
        movies = scrape_sacnilk_movies('https://sacnilk.com/entertainmenttopbar/Recent_Movies')
        
        if not movies:
            logger.info("No recent movies found")
            return
        
        logger.info(f"Found {len(movies)} recent movies on page")
        
        created_count = 0
        transitioned_count = 0
        
        for movie_data in movies:
            try:
                title = movie_data.get('title')
                sacnilk_url = movie_data.get('sacnilk_source_url')

                if not title or not sacnilk_url:
                    continue

                # Scrape details first to get release_date (not available on listing page)
                details = scrape_movie_details(sacnilk_url)
                if not details or not details.get('release_date'):
                    logger.info(f"Skipping {title}: no release_date found")
                    continue

                release_date = details['release_date']
                movie_data.update(details)

                # Skip if older than 7 days
                if release_date < seven_days_ago:
                    continue

                logger.info(f"Processing: {title} (Released: {release_date})")
                
                # Check if movie exists
                result = directus_get(
                    f"/items/movies?filter[sacnilk_source_url][_eq]={sacnilk_url}&limit=1"
                )
                
                existing = result.get('data', [])
                
                if existing:
                    # Movie exists - check status
                    movie = existing[0]
                    movie_id = movie['id']
                    current_status = movie.get('status')
                    
                    logger.info(f"Movie exists: {title} (status: {current_status})")
                    
                    # If still announced, transition to running
                    if current_status == 'announced':
                        logger.info(f"Transitioning {title} to running")
                        
                        # Update status
                        directus_patch(f"/items/movies/{movie_id}", {'status': 'running'})
                        
                        # Check if hub exists
                        hub_result = directus_get(
                            f"/items/box_office_hubs?filter[movie_id][_eq]={movie_id}&limit=1"
                        )
                        
                        if not hub_result.get('data'):
                            # Create hub
                            hub_data = generate_hub_content(movie)
                            hub_payload = {
                                'movie_id': movie_id,
                                'main_content': hub_data.get('main_content', ''),
                                'meta_title': hub_data.get('meta_title', f"{title} Box Office Collection"),
                                'meta_description': hub_data.get('meta_description', ''),
                                'slug': slugify(f"{title}-box-office-collection"),
                                'tags': [title, 'box office collection']
                            }
                            directus_post('/items/box_office_hubs', hub_payload)
                            logger.info(f"✅ Hub created for {title}")
                        
                        # Create missing day pages
                        create_missing_day_pages(movie_id, title, release_date)
                        
                        transitioned_count += 1
                    
                    elif current_status == 'running':
                        # Just ensure all day pages exist
                        create_missing_day_pages(movie_id, title, release_date)
                    
                else:
                    # Movie doesn't exist - create it as running
                    logger.info(f"Creating new movie: {title}")
                    
                    # details already scraped above — no need to re-scrape
                    
                    # Process cast & crew
                    cast_ids = []
                    for person_data in movie_data.get('cast_and_crew', []):
                        person_id = get_or_create_person(
                            name=person_data.get('name', '').strip(),
                            types=person_data.get('types', []),
                            sacnilk_url=person_data.get('sacnilk_url')
                        )
                        if person_id and person_id not in cast_ids:
                            cast_ids.append(person_id)
                    
                    # Humanize plot
                    raw_summary = movie_data.get('summary', '')
                    if raw_summary:
                        humanized_plot = humanize_plot(raw_summary, title)
                        movie_data['plot'] = humanized_plot
                    
                    # Upload poster (don't fail if fails)
                    poster_uuid = None
                    poster_url = movie_data.get('poster')  # scrape_movie_details returns key 'poster', not 'poster_url'
                    if poster_url and poster_url.startswith('http'):
                        try:
                            poster_uuid = upload_file_to_directus(file_url=poster_url, title=slugify(title))
                            if poster_uuid:
                                logger.info(f"✅ Poster uploaded: {poster_uuid}")
                        except Exception as e:
                            logger.warning(f"⚠️ Poster upload failed: {e}")
                    
                    # Create movie as RUNNING
                    create_data = {
                        'status': 'running',
                        'title': title,
                        'slug': movie_data.get('slug'),
                        'release_date': release_date,
                        'language': movie_data.get('languages', ''),
                        'genre': movie_data.get('genre', ''),
                        'sacnilk_source_url': sacnilk_url,
                        'poster': poster_uuid,
                        'budget': movie_data.get('budget', 0),
                        'plot': movie_data.get('plot', ''),
                        'runtime': movie_data.get('runtime'),
                        'cbfc_rating': movie_data.get('cbfc_rating'),
                        'ott_platform': movie_data.get('ott_platform'),
                        'ott_release_date': movie_data.get('ott_release_date'),
                        'cast_crew': [{'people_id': pid} for pid in cast_ids],
                        'tags': movie_data.get('tags', [])
                    }
                    
                    result = directus_post('/items/movies', create_data)

                    if not result or not result.get('data'):
                        logger.error(f"Failed to create movie in Directus: {title}")
                        continue

                    movie_id = result.get('data', {}).get('id')
                    
                    if movie_id:
                        logger.info(f"✅ Created movie: {title} ({movie_id})")
                        
                        # Create hub
                        hub_data = generate_hub_content(movie_data)
                        hub_payload = {
                            'movie_id': movie_id,
                            'main_content': hub_data.get('main_content', ''),
                            'meta_title': hub_data.get('meta_title', f"{title} Box Office Collection"),
                            'meta_description': hub_data.get('meta_description', ''),
                            'slug': slugify(f"{title}-box-office-collection"),
                            'tags': [title, 'box office collection']
                        }
                        directus_post('/items/box_office_hubs', hub_payload)
                        
                        # Create all day pages
                        create_missing_day_pages(movie_id, title, release_date)
                        
                        # Slack notification
                        send_new_movie_notification(movie_data, movie_id)
                        
                        created_count += 1
                
                time.sleep(random.uniform(1, 2))
                
            except Exception as e:
                logger.error(f"Error processing {title}: {e}")
                continue
        
        logger.info(f"Recent movies complete: {created_count} created, {transitioned_count} transitioned")
        
    except Exception as e:
        logger.error(f"Recent movies discovery failed: {e}")


def create_missing_day_pages(movie_id: str, title: str, release_date: str):
    """Create all missing day pages from Day 1 to today"""
    try:
        today = datetime.now().date()
        today_str = today.strftime('%Y-%m-%d')
        
        current_day = calculate_day_number(release_date, today_str)
        
        logger.info(f"Creating missing day pages for {title} (Day 1 to Day {current_day})")
        
        for day in range(1, current_day + 1):
            # Check if exists
            existing = directus_get(
                f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[day_number][_eq]={day}&limit=1"
            )
            
            if existing.get('data'):
                continue
            
            # Create page
            day_date = (datetime.strptime(release_date, '%Y-%m-%d') + timedelta(days=day - 1)).strftime('%Y-%m-%d')
            
            stats_payload = {
                'movie_id': movie_id,
                'day_number': day,
                'date': day_date,
                'india_net': 0,
                'is_estimate': True,
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
                
                logger.info(f"✅ Created Day {day} page")
        
    except Exception as e:
        logger.error(f"Create missing pages failed: {e}")

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

        result = directus_get("/items/movies?filter[status][_eq]=running&limit=1000&fields=id,title,release_date,sacnilk_source_url,budget,india_gross_total,overseas_total")
        running_movies = result.get('data', [])

        if not running_movies:
            logger.info("No running movies")
            return

        logger.info(f"Processing {len(running_movies)} running movies")

        created_count = 0
        closed_count = 0
        skipped_count = 0

        for movie in running_movies:
            try:
                movie_id = movie['id']
                title = movie.get('title')
                release_date = movie.get('release_date')
                sacnilk_url = movie.get('sacnilk_source_url')

                day_number = calculate_day_number(release_date, today_str)

                logger.info(f"{title}: Day {day_number}")

                if day_number <= 0:
                    logger.warning(f"Skipping {title}: Day {day_number}")
                    continue

                # Check if today's page already exists
                existing = directus_get(
                    f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[day_number][_eq]={day_number}&limit=1"
                )

                if existing.get('data'):
                    logger.info(f"Day {day_number} already exists")
                    continue

                # Single scrape — feeds both gap check and Sacnilk gate
                parsed_live = None
                if sacnilk_url:
                    html = get_page_content(sacnilk_url)
                    if html:
                        parsed_live = parse_box_office_table(html)

                # Gap check — close movie if Sacnilk stopped tracking (3+ day gap)
                if parsed_live and parsed_live.get('days'):
                    actual_max_day = max(d['day_number'] for d in parsed_live['days'])
                    release = datetime.strptime(release_date, "%Y-%m-%d")
                    expected_days = (datetime.now() - release).days
                    gap = expected_days - actual_max_day
                    logger.info(f"{title} — Sacnilk max: Day {actual_max_day}, Expected: Day {expected_days}, Gap: {gap}")

                    if gap >= 3:
                        close_movie_and_calculate_verdict(movie_id, movie, parsed_live)
                        closed_count += 1
                        continue
                else:
                    # Can't scrape — assume still running, don't close
                    logger.warning(f"Could not scrape {title} — skipping gap check")

                # Sacnilk gate — only create Day N if Sacnilk has Day N-1
                if parsed_live and day_number > 1:
                    max_sacnilk_day = max((d['day_number'] for d in parsed_live.get('days', [])), default=0)
                    prev_day = day_number - 1
                    if max_sacnilk_day < prev_day:
                        logger.warning(
                            f"Skipping Day {day_number} for '{title}': "
                            f"Sacnilk only has up to Day {max_sacnilk_day}, need Day {prev_day}"
                        )
                        skipped_count += 1
                        continue
                    else:
                        logger.info(f"Sacnilk has Day {max_sacnilk_day} ✅ — safe to create Day {day_number}")

                # Create today's page
                stats_payload = {
                    'movie_id': movie_id,
                    'day_number': day_number,
                    'date': today_str,
                    'india_net': 0,
                    'is_estimate': True,
                    'slug': slugify(f"{title}-day-{day_number}-box-office-collection"),
                    'tags': [title, f"day {day_number}", "box office"]
                }

                result = directus_post('/items/daily_stats', stats_payload)

                if result.get('data'):
                    created_count += 1
                    enqueue_job('queue:content_generation', {
                        'type': 'daily_box_office_prediction',
                        'movie_id': movie_id,
                        'day_number': day_number,
                        'movie_title': title,
                        'mode': 'prediction'
                    })
                    logger.info(f"✅ Created Day {day_number} page for {title}")

                time.sleep(random.uniform(1, 2))

            except Exception as e:
                logger.error(f"Error processing {title}: {e}")
                continue

        logger.info(f"Daily pages complete: {created_count} created, {closed_count} closed, {skipped_count} skipped (Sacnilk not ready)")

    except Exception as e:
        logger.error(f"Daily pages failed: {e}")


def check_movie_still_tracked(movie: Dict, parsed: Dict = None) -> bool:
    """Check if Sacnilk still tracking (3-day gap check)"""
    try:
        sacnilk_url = movie.get('sacnilk_source_url')
        release_date = movie.get('release_date')

        if not sacnilk_url or not release_date:
            return True

        if not parsed:
            html = get_page_content(sacnilk_url)
            if not html:
                return True
            parsed = parse_box_office_table(html)

        if not parsed or not parsed.get('days'):
            return True

        actual_max_day = max(d['day_number'] for d in parsed['days'])
        release = datetime.strptime(release_date, "%Y-%m-%d")
        expected_days = (datetime.now() - release).days
        gap = expected_days - actual_max_day

        logger.info(f"Sacnilk max: Day {actual_max_day}, Expected: Day {expected_days}, Gap: {gap}")

        return gap < 3

    except Exception as e:
        logger.error(f"Gap check failed: {e}")
        return True


def close_movie_and_calculate_verdict(movie_id: str, movie: Dict, parsed_live: Dict = None):
    """Close movie and calculate verdict using final scraped figures"""
    try:
        title = movie.get('title')
        budget = movie.get('budget', 0)
        sacnilk_url = movie.get('sacnilk_source_url')

        # Use already-scraped data if passed, otherwise re-scrape for final figures
        india_gross = movie.get('india_gross_total', 0)
        overseas = movie.get('overseas_total', 0)

        if not parsed_live and sacnilk_url:
            html = get_page_content(sacnilk_url)
            if html:
                parsed_live = parse_box_office_table(html)

        if parsed_live and parsed_live.get('totals'):
            totals = parsed_live['totals']
            if totals.get('india_gross_total'):
                india_gross = totals['india_gross_total']
            if totals.get('overseas_total'):
                overseas = totals['overseas_total']

            # Update Directus with final figures before closing
            directus_patch(f"/items/movies/{movie_id}", {
                'india_gross_total': india_gross,
                'overseas_total': overseas
            })

        verdict = 'pending'

        if budget > 0 and india_gross > 0:
            ratio = (india_gross / budget) * 100  # as percentage of budget
            if ratio >= 200:
                verdict = 'blockbuster'
            elif ratio >= 150:
                verdict = 'super_hit'
            elif ratio >= 100:
                verdict = 'hit'
            elif ratio >= 75:
                verdict = 'average'
            elif ratio >= 50:
                verdict = 'below_average'
            elif ratio >= 25:
                verdict = 'flop'
            else:
                verdict = 'disaster'

        directus_patch(f"/items/movies/{movie_id}", {
            'status': 'closed',
            'verdict': verdict
        })

        logger.info(f"✅ Closed: {title} — India Gross: ₹{india_gross} Cr, Budget: ₹{budget} Cr, Verdict: {verdict.upper()}")

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "🏁 MOVIE CLOSED"}},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"*{title}*\nIndia Gross: ₹{india_gross} Cr\nBudget: ₹{budget} Cr\nVerdict: *{verdict.upper()}*"
            }}
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
                today = datetime.now().date()
                today_str = today.strftime('%Y-%m-%d')
                three_days_ago = (today - timedelta(days=3)).strftime('%Y-%m-%d')

                for day_data in parsed['days']:
                    day_number = day_data['day_number']
                    day_page_href = day_data.get('day_page_href', '')

                    # PRIMARY: fetch individual day page for consolidated india_net
                    india_net = 0
                    if day_page_href:
                        try:
                            day_url = f"https://sacnilk.com{day_page_href}"
                            day_html = get_page_content(day_url)
                            if day_html:
                                day_parsed = parse_box_office_table(day_html)
                                # Individual day page returns days list with the
                                # consolidated figure for that specific day
                                if day_parsed and day_parsed.get('days'):
                                    match = next(
                                        (d for d in day_parsed['days'] if d['day_number'] == day_number),
                                        None
                                    )
                                    if match and match['india_net'] > 0:
                                        india_net = match['india_net']
                                        logger.info(f"Day {day_number}: ₹{india_net} Cr [from day page]")
                        except Exception as e:
                            logger.warning(f"Day page fetch failed for Day {day_number}: {e}")

                    # FALLBACK: use summed language data from movie page
                    if not india_net:
                        india_net = day_data.get('india_net', 0)
                        if india_net:
                            logger.info(f"Day {day_number}: ₹{india_net} Cr [summed from language sections]")

                    if not india_net:
                        logger.warning(f"Day {day_number}: no data from either source, skipping")
                        continue

                    # Check if exists in Directus
                    result = directus_get(
                        f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&filter[day_number][_eq]={day_number}&limit=1"
                    )
                    existing = result.get('data', [])

                    if existing:
                        stats = existing[0]
                        day_date = stats.get('date', '')
                        old_net = stats.get('india_net', 0)

                        if day_date >= three_days_ago:
                            changed = abs((old_net or 0) - (india_net or 0)) > 0.01
                            is_now_actual = stats.get('is_estimate', True) and india_net > 0

                            if changed or is_now_actual:
                                directus_patch(f"/items/daily_stats/{stats['id']}", {
                                    'india_net': india_net,
                                    'is_estimate': day_date == today_str
                                })
                                logger.info(f"Updated Day {day_number}: ₹{old_net} → ₹{india_net} Cr")

                                if changed and india_net > 0:
                                    enqueue_job('queue:content_generation', {
                                        'type': 'daily_box_office_actual',
                                        'movie_id': movie_id,
                                        'day_number': day_number,
                                        'movie_title': title,
                                        'mode': 'actual',
                                        'india_net': india_net
                                    })
                    else:
                        # Backfill missing day
                        if day_number == 0:
                            day_date = (datetime.strptime(release_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
                        else:
                            day_date = (datetime.strptime(release_date, '%Y-%m-%d') + timedelta(days=day_number - 1)).strftime('%Y-%m-%d')

                        stats_payload = {
                            'movie_id': movie_id,
                            'day_number': day_number,
                            'date': day_date,
                            'india_net': india_net,
                            'is_estimate': False,
                            'slug': slugify(f"{title}-day-{day_number}-box-office-collection"),
                            'tags': [title, f"day {day_number}", "box office"]
                        }

                        result = directus_post('/items/daily_stats', stats_payload)
                        if result and result.get('data'):
                            enqueue_job('queue:content_generation', {
                                'type': 'daily_box_office_actual',
                                'movie_id': movie_id,
                                'day_number': day_number,
                                'movie_title': title,
                                'mode': 'actual',
                                'india_net': india_net
                            })
                            logger.info(f"Backfilled Day {day_number}: ₹{india_net} Cr")

                # Update movie totals from parsed totals row
                totals_update = {}
                if parsed.get('totals'):
                    if 'india_gross_total' in parsed['totals']:
                        totals_update['india_gross_total'] = parsed['totals']['india_gross_total']
                    if 'overseas_total' in parsed['totals']:
                        totals_update['overseas_total'] = parsed['totals']['overseas_total']

                # FIX: Fallback — if totals row missing, sum india_net from all parsed days
                if 'india_gross_total' not in totals_update and parsed.get('days'):
                    total_net = sum(d.get('india_net', 0) for d in parsed['days'])
                    if total_net > 0:
                        totals_update['india_gross_total'] = total_net
                        logger.info(f"Totals row missing — computed india_gross_total from daily sum: ₹{total_net} Cr")

                if totals_update:
                    directus_patch(f"/items/movies/{movie_id}", totals_update)
                    logger.info(f"Updated movie totals: {totals_update}")
                
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

                        # FIX: Re-queue SEO content with corrected actual figure
                        if new_value > 0:
                            enqueue_job('queue:content_generation', {
                                'type': 'daily_box_office_actual',
                                'movie_id': movie_id,
                                'day_number': day_number,
                                'movie_title': title,
                                'mode': 'actual',
                                'india_net': new_value
                            })
                            logger.info(f"Re-queued SEO for Day {day_number} after audit correction")
                
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
        
        prompt = f"""Analyze this entertainment news article and match it to known movies and people.

        HEADLINE: {title}
        SNIPPET: {description}

        KNOWN MOVIES:
        {movies_context[:1000]}

        KNOWN PEOPLE:
        {people_context[:1000]}

        Return ONLY valid JSON, no explanation:
        {{
        "is_relevant": true/false,
        "confidence": 0.0-1.0,
        "movie_ids": [],
        "people_ids": [],
        "category": "news|review|ott"
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
        discover_recent_movies()
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