"""
worker.py - Content generation queue processor
Processes jobs from Redis queue:
- News articles (5 stages: Tavily → Gen → Humanize → SEO → Image)
- Daily box office (3 stages: Gen → Humanize → SEO)
- Hub content (already generated in scheduler, not queued)
- Plot humanization (already generated in scheduler, not queued)
"""

import sys
import os
from common import *
from datetime import datetime
import time
import re

# ============================================================================
# NEWS ARTICLE PROCESSOR (5 STAGES)
# ============================================================================

def process_news_article(job_data: Dict) -> bool:
    """
    Generate news article (5 stages: Tavily → Gen → Humanize → SEO → Image)
    Returns: True if successful
    """
    try:
        lead_id = job_data.get('lead_id')
        movie_ids = job_data.get('movie_ids', [])
        people_ids = job_data.get('people_ids', [])
        category_id = job_data.get('category_id')
        response_url = job_data.get('response_url')
        
        logger.info(f"Processing news article: Lead {lead_id}")
        
        # Fetch lead
        lead_result = directus_get(f"/items/news_leads/{lead_id}")
        lead = lead_result.get('data', {})
        
        title = lead.get('title', '')
        source_url = lead.get('source_url', '')
        
        # Fetch movie details
        movie_titles = []
        for mid in movie_ids:
            result = directus_get(f"/items/movies/{mid}?fields=title,slug")
            movie = result.get('data', {})
            if movie:
                movie_titles.append(movie.get('title', ''))
        
        # Fetch people details
        people_names = []
        for pid in people_ids:
            result = directus_get(f"/items/people/{pid}?fields=name,slug")
            person = result.get('data', {})
            if person:
                people_names.append(person.get('name', ''))
        
        # Fetch category WITH prompt
        category_result = directus_get(f"/items/categories/{category_id}?fields=*")
        category = category_result.get('data', {})
        category_name = category.get('name', 'News')
        category_prompt = category.get('prompt_generation', '')
        
        logger.info(f"Title: {title}")
        logger.info(f"Movies: {movie_titles}")
        logger.info(f"People: {people_names}")
        logger.info(f"Category: {category_name}")
        
        # STAGE 0: Tavily Research
        query = f"{title} {' '.join(movie_titles)} {' '.join(people_names)}"
        research_context = tavily_research(query)
        
        # STAGE 1: Generation (with category prompt)
        if category_prompt:
            generation_prompt = category_prompt.format(
                title=title,
                source_url=source_url,
                movie_titles=', '.join(movie_titles) if movie_titles else 'None',
                people_names=', '.join(people_names) if people_names else 'None',
                category_name=category_name,
                research_context=research_context[:2000]
            )
            logger.info("Using category-specific prompt")
        else:
            logger.warning("No category prompt, using default")
            generation_prompt = f"""Generate a comprehensive article based on this news.

HEADLINE: {title}
SOURCE: {source_url}

MOVIES: {', '.join(movie_titles) if movie_titles else 'None'}
PEOPLE: {', '.join(people_names) if people_names else 'None'}
CATEGORY: {category_name}

RESEARCH:
{research_context[:2000]}

Generate 800-1000 word article with:
- Engaging introduction
- Detailed body with facts
- Quotes if available
- Analysis and context
- Conclusion
- FAQ section (4-5 questions)

For REVIEW: Include rating, pros/cons, verdict
For NEWS: Latest updates, industry impact
For OTT: Platform details, release info

Return only the article text (not HTML yet)."""
        
        draft = stage_generation(generation_prompt, 'news')
        if not draft:
            raise Exception("Generation failed")
        
        # STAGE 2: Humanization
        humanized = stage_humanize(draft, 'news')
        if not humanized:
            logger.warning("Humanization failed, using draft")
            humanized = draft
        
        # Extract people from content
        all_people_ids = extract_people_from_text(humanized, people_ids)
        
        # STAGE 3: SEO
        seo_data = stage_seo(humanized, title, 'news')
        if not seo_data:
            raise Exception("SEO optimization failed")
        
        # Add interlinking
        content_with_links = add_internal_links(seo_data.get('content', ''), {
            'movie_ids': movie_ids,
            'people_ids': all_people_ids,
            'current_slug': slugify(title)
        })
        
        seo_data['content'] = content_with_links
        
        # STAGE 4: Image Generation
        image_uuid = stage_image_generation(title)
        
        # Extract rating/punchline for reviews
        rating = None
        rating_out_of = None
        punchline = None
        
        if category_name.lower() == 'review':
            rating_match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+)', humanized)
            if rating_match:
                rating = float(rating_match.group(1))
                rating_out_of = int(rating_match.group(2))
            
            lines = humanized.split('\n')
            for line in lines[:10]:
                if 20 < len(line) < 150:
                    punchline = line.strip()
                    break
        
        # Generate tags
        tags = movie_titles + people_names + [category_name]
        
        # Create news_articles entry
        article_data = {
            'movie_id': movie_ids if movie_ids else [],
            'people_id': all_people_ids if all_people_ids else [],
            'category': category_id,
            'title': seo_data.get('meta_title', title),
            'slug': slugify(seo_data.get('meta_title', title)),
            'content': seo_data.get('content', humanized),
            'tags': tags,
            'status': 'published'
        }
        
        if image_uuid:
            article_data['image'] = image_uuid
        
        if rating:
            article_data['rating'] = rating
            article_data['rating_out_of'] = rating_out_of
        
        if punchline:
            article_data['punchline'] = punchline
        
        if seo_data.get('meta_description'):
            article_data['meta_description'] = seo_data['meta_description'][:155]
        
        result = directus_post('/items/news_articles', article_data)
        article_id = result.get('data', {}).get('id')
        
        if not article_id:
            raise Exception("Failed to create article")
        
        # Update lead status
        directus_patch(f"/items/news_leads/{lead_id}", {'status': 'processed'})
        
        logger.info(f"✅ News article published: {article_id}")
        
        # Send ephemeral notification
        if response_url:
            slack_ephemeral(response_url, f"✅ Published: {title}")
        
        return True
        
    except Exception as e:
        logger.error(f"News article job failed: {e}")
        
        if job_data.get('response_url'):
            slack_ephemeral(job_data['response_url'], f"❌ Error: {str(e)}")
        
        return False

# ============================================================================
# DAILY BOX OFFICE PROCESSOR (3 STAGES)
# ============================================================================

def process_daily_box_office(job_data: Dict) -> bool:
    """
    Generate daily box office article (3 stages: Gen → Humanize → SEO)
    Returns: True if successful
    """
    try:
        movie_id = job_data.get('movie_id')
        day_number = job_data.get('day_number')
        movie_title = job_data.get('movie_title')
        mode = job_data.get('mode', 'prediction')
        india_net = job_data.get('india_net', 0)
        
        logger.info(f"Processing daily box office: {movie_title} Day {day_number} ({mode})")
        
        # Fetch movie details
        movie_result = directus_get(f"/items/movies/{movie_id}")
        movie = movie_result.get('data', {})
        
        # Fetch all daily_stats
        stats_result = directus_get(
            f"/items/daily_stats?filter[movie_id][_eq]={movie_id}&sort=day_number&limit=100"
        )
        daily_stats = stats_result.get('data', [])
        
        # Build data table
        table_rows = []
        for stat in daily_stats:
            if stat['day_number'] < day_number:
                table_rows.append(f"Day {stat['day_number']}: ₹{stat.get('india_net', 0)} Cr")
        
        table_text = "\n".join(table_rows) if table_rows else "No previous data"
        
        # Build prompt
        if mode == 'prediction':
            prompt = f"""Generate a Day {day_number} box office PREDICTION article for {movie_title}.

MOVIE DETAILS:
- Title: {movie_title}
- Budget: ₹{movie.get('budget', 'Unknown')} Cr
- Genre: {', '.join(movie.get('genre', []))}
- Languages: {', '.join(movie.get('language', []))}
- India Gross so far: ₹{movie.get('india_gross_total', 0)} Cr
- Overseas so far: ₹{movie.get('overseas_total', 0)} Cr

PREVIOUS DAYS:
{table_text}

Generate 800-word article with:
- Expected collection range
- Factors affecting performance
- Comparison with previous days
- Industry trends
- FAQ section

Use phrases: "expected to collect", "predicted", "estimated"

Return only the article text (not HTML yet)."""
        else:
            prompt = f"""Generate a Day {day_number} box office ACTUAL article for {movie_title}.

MOVIE DETAILS:
- Title: {movie_title}
- Budget: ₹{movie.get('budget', 'Unknown')} Cr

DAY {day_number} COLLECTION:
- India Net: ₹{india_net} Cr

PREVIOUS DAYS:
{table_text}

TOTAL SO FAR:
- India Gross: ₹{movie.get('india_gross_total', 0)} Cr
- Overseas: ₹{movie.get('overseas_total', 0)} Cr

Generate 800-word article with:
- Day {day_number} collection analysis
- Comparison with previous days
- Running total
- HTML table with day-wise breakdown
- FAQ section

Return only the article text (not HTML yet)."""
        
        # STAGE 1: Generation
        draft = stage_generation(prompt, 'daily')
        if not draft:
            raise Exception("Generation failed")
        
        # STAGE 2: Humanization
        humanized = stage_humanize(draft, 'daily')
        if not humanized:
            logger.warning("Humanization failed, using draft")
            humanized = draft
        
        # STAGE 3: SEO
        seo_data = stage_seo(humanized, f"{movie_title} Day {day_number} Box Office Collection", 'daily')
        if not seo_data:
            raise Exception("SEO optimization failed")
        
        # Add interlinking
        content_with_links = add_internal_links(seo_data.get('content', ''), {
            'movie_ids': [movie_id],
            'people_ids': [],
            'day_number': day_number,
            'current_slug': slugify(f"{movie_title}-day-{day_number}")
        })
        
        seo_data['content'] = content_with_links
        
        # Find daily_stats entry
        daily_stat = next((s for s in daily_stats if s['day_number'] == day_number), None)
        
        if not daily_stat:
            logger.error(f"Daily stats entry not found for Day {day_number}")
            return False
        
        # Update daily_stats
        update_data = {
            'seo_content': seo_data.get('content', humanized),
            'meta_title': seo_data.get('meta_title', f"{movie_title} Day {day_number} Collection"),
            'meta_description': seo_data.get('meta_description', f"Day {day_number} box office collection...")[:155]
        }
        
        directus_patch(f"/items/daily_stats/{daily_stat['id']}", update_data)
        
        logger.info(f"✅ Daily box office article published for Day {day_number}")
        return True
        
    except Exception as e:
        logger.error(f"Daily box office job failed: {e}")
        return False

# ============================================================================
# JOB PROCESSOR WITH RETRY
# ============================================================================

def process_job_with_retry(job_data: Dict) -> bool:
    """Process job with 3-attempt retry"""
    job_type = job_data.get('type')
    max_attempts = 3
    
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(f"Attempt {attempt}/{max_attempts} for {job_type}")
            
            if job_type == 'news_article':
                success = process_news_article(job_data)
            elif job_type in ['daily_box_office_prediction', 'daily_box_office_actual']:
                success = process_daily_box_office(job_data)
            else:
                logger.error(f"Unknown job type: {job_type}")
                return False
            
            if success:
                logger.info(f"✅ Job completed on attempt {attempt}")
                return True
            else:
                if attempt < max_attempts:
                    logger.warning(f"Attempt {attempt} failed, retrying...")
                    time.sleep(5 * attempt)
                
        except Exception as e:
            logger.error(f"Attempt {attempt} error: {e}")
            if attempt < max_attempts:
                time.sleep(5 * attempt)
    
    # All attempts failed
    logger.error(f"❌ Job failed after {max_attempts} attempts")
    store_failed_job(job_data)
    return False

# ============================================================================
# MAIN WORKER LOOP
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("CONTENT GENERATION WORKER STARTED")
    logger.info("=" * 60)
    logger.info("Waiting for jobs in queue:content_generation...")
    
    while True:
        try:
            # Block and wait for job (timeout 30 seconds)
            job_data = dequeue_job('queue:content_generation', timeout=30)
            
            if not job_data:
                continue
            
            log_job_start(job_data.get('type', 'unknown'), job_data)
            
            # Process with retry
            success = process_job_with_retry(job_data)
            
            if success:
                log_job_complete(job_data.get('type', 'unknown'))
            else:
                log_job_failed(job_data.get('type', 'unknown'), "All retry attempts failed")
            
        except KeyboardInterrupt:
            logger.info("\nShutting down worker...")
            break
        except Exception as e:
            logger.error(f"Fatal error in worker: {e}")
            time.sleep(5)