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
                research_context=research_context[:3000]
            )
            logger.info("Using category-specific prompt")
        else:
            logger.warning("No category prompt, using default")
            generation_prompt = f"""You are a senior entertainment journalist writing for a high-traffic film news publication.

            HEADLINE: {title}
            SOURCE: {source_url}
            CATEGORY: {category_name}
            MOVIES: {', '.join(movie_titles) if movie_titles else 'None'}
            PEOPLE: {', '.join(people_names) if people_names else 'None'}

            RESEARCH:
            {research_context[:3000]}

            Write a 1000-1200 word article in HTML based on the research above.

            STRUCTURE:
            <h2>Opening</h2> — Lead with the most newsworthy detail, not the headline reworded. First sentence must make the reader want to continue.
            <h2>The Full Story</h2> — Expand with facts, context, and implications drawn strictly from the research. Attribute claims to sources where possible.
            <h2>Key Details</h2> — Supporting facts, relevant background, industry context. Use <blockquote> for any direct quotes found in research.
            <h2>What This Means</h2> — Analyst perspective: why this matters for the film, the people involved, or the industry.
            <h2>Frequently Asked Questions</h2> — 4-5 FAQs as <strong>Q: question</strong> followed by <p>answer</p> covering what readers would search next.

            CATEGORY-SPECIFIC:
            - NEWS: Focus on latest developments, timeline, industry impact
            - REVIEW: Add <h2>Verdict</h2> with a clear rating and pros/cons in <ul>
            - OTT: Include platform name, release date, regions, and availability details prominently

            RULES:
            - Never invent quotes, facts, or figures not present in the research
            - If research is thin, write what's known and acknowledge what's unclear — never pad with speculation
            - All people and movie names must match exactly as provided above

            AVOID: "It's worth noting", "Delve into", "Remarkable", "Testament to", "Needless to say", "In conclusion", "To summarize".
            HTML only — no <html>/<body> wrappers, no inline styles, no markdown fences."""
        
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
            prompt = f"""You are a senior entertainment journalist writing for an Indian film trade publication.

        MOVIE: {movie_title} | Budget: ₹{budget or 'N/A'} Cr | Genre: {genre} | Languages: {languages}
        TOTALS SO FAR: India Gross ₹{india_gross} Cr | Overseas ₹{overseas} Cr
        PREVIOUS DAYS TREND:
        {table_text}

        Write a Day {day_number} box office prediction article (~800 words) in HTML.

        PURPOSE: This is an SEO article — write for readers searching "{movie_title} Day {day_number} box office prediction". 
        Do NOT repeat raw day-wise data in the content — that data is already displayed in a separate table on the page.
        Focus on storytelling, context, and analysis that a reader genuinely wants to read.

        STRUCTURE:
        <h2>What to Expect on Day {day_number}</h2> — Why this particular day matters for the film's run. Weekend vs weekday dynamics, competition, word of mouth momentum. Give a predicted range naturally within the prose.
        <h2>How the Film Has Performed So Far</h2> — Narrative summary of the film's run without listing every day's figure. Talk about the overall trend — strong hold, sharp drop, steady weekday performance etc.
        <h2>Factors That Will Shape Day {day_number}</h2> — 3-4 specific factors written as flowing paragraphs: audience reception, competition from new releases, regional vs national performance, multiplex vs single screen split.
        <h2>Can {movie_title} Hit Its Target?</h2> — Budget recovery context, what milestone the film is chasing, realistic assessment of its overall run based on current trajectory.
        <h2>Frequently Asked Questions</h2> — 5 FAQs written as <strong>Q: question</strong> followed by <p>answer</p>. Cover: Day {day_number} prediction, running total, overseas performance, budget recovery, overall verdict.

        TONE: Analytical and conversational — like a knowledgeable trade writer, not a data sheet.
        LANGUAGE: Use "expected", "likely", "projected" for predictions. Give ranges not single figures.
        AVOID: Listing every day's collection figure. Raw data tables. "It's worth noting", "Delve into", "Remarkable", "Testament to", "Needless to say", "highly anticipated", "magnum opus".
        HTML only — no <html>/<body> wrappers, no inline styles, no markdown fences."""

        else:
            prompt = f"""You are a senior entertainment journalist writing for an Indian film trade publication.

        MOVIE: {movie_title} | Budget: ₹{budget or 'N/A'} Cr | Genre: {genre} | Languages: {languages}
        DAY {day_number}: India Net ₹{india_net} Cr
        TOTALS: India Gross ₹{india_gross} Cr | Overseas ₹{overseas} Cr | Worldwide ₹{worldwide} Cr
        {roi_line}
        PREVIOUS DAYS TREND:
        {table_text}

        Write a Day {day_number} box office collection article (~800 words) in HTML.

        PURPOSE: This is an SEO article — write for readers searching "{movie_title} Day {day_number} box office collection".
        Do NOT repeat raw day-wise data in the content — that data is already displayed in a separate table on the page.
        Focus on what the numbers mean, not what the numbers are.

        STRUCTURE:
        <h2>{movie_title} Day {day_number} Box Office — How Did It Do?</h2> — Open with a one-sentence verdict on Day {day_number} (strong hold / expected drop / surprise jump). Mention ₹{india_net} Cr naturally in prose, then immediately give context: is this good or bad for a film of this budget and genre on this day of its run?
        <h2>Reading the Trend</h2> — Analyse the overall trajectory without listing every figure. Is the film holding well? Dropping sharply? Recovering after a mid-week dip? What does the pattern tell us about audience behaviour and word of mouth?
        <h2>Where Does It Stand Against Its Budget?</h2> — Budget recovery story in plain language. How close is it to breaking even? Is it already profitable? What does it need to hit to be called a hit, average, or flop by trade standards?
        <h2>The Road Ahead</h2> — Realistic first week estimate, lifetime projection, and what would need to happen for the film to exceed or fall short of those projections. Ground it in the trend data.
        <h2>Frequently Asked Questions</h2> — 5 FAQs as <strong>Q: question</strong> followed by <p>answer</p>. Cover: Day {day_number} collection, running total, worldwide gross, budget recovery status, is the film a hit or flop.

        TONE: Analytical and conversational — like a knowledgeable trade writer giving their honest read.
        AVOID: Listing every day's collection figure. Raw data tables. "It's worth noting", "Delve into", "Remarkable", "Testament to", "Needless to say", "highly anticipated".
        HTML only — no <html>/<body> wrappers, no inline styles, no markdown fences."""
        
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