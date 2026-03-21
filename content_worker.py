# ============================================================================
# AI PIPELINE STAGES
# ============================================================================

def stage_generation(prompt: str, pipeline_type: str) -> Optional[str]:
    """
    Stage 1: Generate draft content
    pipeline_type: 'news', 'plot', 'daily', 'hub'
    """
    try:
        logger.info(f"STAGE 1: Generation ({pipeline_type})")
        
        # Select model based on pipeline type
        if pipeline_type == 'news':
            model = get_setting("news_generation_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("news_generation_temperature", 0.7)
            max_tokens = get_setting("news_generation_max_tokens", 8000)
        elif pipeline_type == 'plot':
            model = get_setting("plot_generation_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("plot_generation_temperature", 0.7)
            max_tokens = get_setting("plot_generation_max_tokens", 2000)
        elif pipeline_type == 'daily':
            model = get_setting("daily_generation_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("daily_generation_temperature", 0.7)
            max_tokens = get_setting("daily_generation_max_tokens", 4000)
        elif pipeline_type == 'hub':
            model = get_setting("hub_generation_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("hub_generation_temperature", 0.7)
            max_tokens = get_setting("hub_generation_max_tokens", 4000)
        else:
            raise ValueError(f"Unknown pipeline type: {pipeline_type}")
        
        result = call_openrouter(model, prompt, temperature, max_tokens)
        
        if not result:
            # Try fallback model
            fallback_model = get_setting("fallback_generation_model", "openai/gpt-4-turbo")
            logger.warning(f"Primary model failed, trying fallback: {fallback_model}")
            result = call_openrouter(fallback_model, prompt, temperature, max_tokens)
        
        return result
        
    except Exception as e:
        logger.error(f"Generation stage failed: {e}")
        return None


def stage_humanize(draft_content: str, pipeline_type: str) -> Optional[str]:
    """
    Stage 2: Humanize content
    pipeline_type: 'news', 'plot', 'daily', 'hub'
    """
    try:
        logger.info(f"STAGE 2: Humanization ({pipeline_type})")
        
        # Select model based on pipeline type
        if pipeline_type == 'news':
            model = get_setting("news_humanize_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("news_humanize_temperature", 0.8)
            max_tokens = get_setting("news_humanize_max_tokens", 8000)
        elif pipeline_type == 'plot':
            model = get_setting("plot_humanize_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("plot_humanize_temperature", 0.8)
            max_tokens = get_setting("plot_humanize_max_tokens", 2000)
        elif pipeline_type == 'daily':
            model = get_setting("daily_humanize_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("daily_humanize_temperature", 0.8)
            max_tokens = get_setting("daily_humanize_max_tokens", 4000)
        elif pipeline_type == 'hub':
            model = get_setting("hub_humanize_model", "anthropic/claude-3.5-sonnet")
            temperature = get_setting("hub_humanize_temperature", 0.8)
            max_tokens = get_setting("hub_humanize_max_tokens", 4000)
        else:
            raise ValueError(f"Unknown pipeline type: {pipeline_type}")
        
        prompt = f"""Rewrite this content to sound more natural and human.

CONTENT:
{draft_content}

REQUIREMENTS:
- Remove AI-like phrases: "It's worth noting", "Interestingly", "Needless to say", "Delve into"
- Use varied sentence structures
- Add conversational flow
- Keep all facts and data intact
- Maintain SEO optimization
- Use active voice
- Professional journalistic tone

Return only the rewritten content, no extra text."""
        
        result = call_openrouter(model, prompt, temperature, max_tokens)
        
        if not result:
            fallback_model = get_setting("fallback_humanize_model", "openai/gpt-4-turbo")
            logger.warning(f"Humanize model failed, trying fallback: {fallback_model}")
            result = call_openrouter(fallback_model, prompt, temperature, max_tokens)
        
        return result
        
    except Exception as e:
        logger.error(f"Humanization stage failed: {e}")
        return None


def stage_seo(humanized_content: str, title: str, pipeline_type: str) -> Optional[Dict]:
    """
    Stage 3: SEO optimization
    pipeline_type: 'news', 'daily', 'hub' (NOT plot)
    """
    try:
        logger.info(f"STAGE 3: SEO Optimization ({pipeline_type})")
        
        # Select model based on pipeline type
        if pipeline_type == 'news':
            model = get_setting("news_seo_model", "openai/gpt-4-turbo")
            temperature = get_setting("news_seo_temperature", 0.5)
            max_tokens = get_setting("news_seo_max_tokens", 4000)
        elif pipeline_type == 'daily':
            model = get_setting("daily_seo_model", "openai/gpt-4-turbo")
            temperature = get_setting("daily_seo_temperature", 0.5)
            max_tokens = get_setting("daily_seo_max_tokens", 2000)
        elif pipeline_type == 'hub':
            model = get_setting("hub_seo_model", "openai/gpt-4-turbo")
            temperature = get_setting("hub_seo_temperature", 0.5)
            max_tokens = get_setting("hub_seo_max_tokens", 2000)
        else:
            raise ValueError(f"SEO not supported for pipeline: {pipeline_type}")
        
        prompt = f"""Optimize this content for SEO.

TITLE: {title}

CONTENT:
{humanized_content}

OPTIMIZE:
1. Add proper H1, H2, H3 headings
2. Create meta title (60 chars max)
3. Create meta description (155 chars max)
4. Ensure keyword density
5. Add FAQ section if not present
6. Optimize for featured snippets

Return ONLY JSON:
{{
  "content": "<h1>...</h1><p>...</p>...",
  "meta_title": "...",
  "meta_description": "..."
}}"""
        
        result = call_openrouter(model, prompt, temperature, max_tokens)
        
        if not result:
            fallback_model = get_setting("fallback_seo_model", "anthropic/claude-3.5-sonnet")
            logger.warning(f"SEO model failed, trying fallback: {fallback_model}")
            result = call_openrouter(fallback_model, prompt, temperature, max_tokens)
        
        if result:
            seo_data = extract_json_from_text(result)
            return seo_data
        
        return None
        
    except Exception as e:
        logger.error(f"SEO stage failed: {e}")
        return None


def stage_image_generation(title: str, content: str) -> Optional[str]:
    """
    Stage 4: Generate featured image (News articles only)
    """
    try:
        logger.info("STAGE 4: Image Generation")
        
        model = get_setting("news_image_model", "black-forest-labs/flux-schnell")
        width = get_setting("news_image_width", 1024)
        height = get_setting("news_image_height", 768)
        
        prompt = f"Professional featured image for article: {title}. Cinematic, high quality, movie poster style."
        
        image_url = call_openrouter_image(model, prompt, width, height)
        
        if not image_url:
            logger.warning("Image generation failed")
            return None
        
        file_uuid = upload_file_to_directus(
            file_url=image_url,
            title=slugify(title)
        )
        
        return file_uuid
        
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return None


# ============================================================================
# JOB: DAILY BOX OFFICE (3 STAGES: Gen → Humanize → SEO)
# ============================================================================

def process_daily_box_office(job_data: Dict) -> bool:
    """
    Generate daily box office article (3 stages)
    Pipeline: Generation → Humanization → SEO
    """
    try:
        movie_id = job_data.get('movie_id')
        day_number = job_data.get('day_number')
        movie_title = job_data.get('movie_title')
        mode = job_data.get('mode', 'prediction')
        
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
        
        current_day_net = job_data.get('india_net', 0) if mode == 'actual' else 0
        
        # Build prompt
        if mode == 'prediction':
            prompt = f"""Generate a Day {day_number} box office PREDICTION article for {movie_title}.

MOVIE DETAILS:
- Title: {movie_title}
- Budget: ₹{movie.get('budget', 'Unknown')} Cr
- Genre: {', '.join(movie.get('genre', []))}
- Languages: {', '.join(movie.get('language', []))}
- Total India Gross so far: ₹{movie.get('india_gross_total', 0)} Cr
- Total Overseas so far: ₹{movie.get('overseas_total', 0)} Cr

PREVIOUS DAYS DATA:
{table_text}

GENERATE 800-word article with:
- H1: {movie_title} Day {day_number} Box Office Prediction
- Expected collection range
- Factors affecting today's performance
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

DAY {day_number} ACTUAL COLLECTION:
- India Net: ₹{current_day_net} Cr

PREVIOUS DAYS DATA:
{table_text}

TOTAL SO FAR:
- India Gross: ₹{movie.get('india_gross_total', 0)} Cr
- Overseas: ₹{movie.get('overseas_total', 0)} Cr

GENERATE 800-word article with:
- Day {day_number} actual collection analysis
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
# JOB: NEWS ARTICLE (5 STAGES: Tavily → Gen → Humanize → SEO → Image)
# ============================================================================

def process_news_article(job_data: Dict) -> bool:
    """
    Generate news article (5 stages)
    Pipeline: Tavily → Generation (with category prompt) → Humanization → SEO → Image
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
            try:
                m = directus_get(f"/items/movies/{mid}")
                movie_titles.append(m.get('data', {}).get('title', ''))
            except:
                pass
        
        # Fetch people details
        people_names = []
        for pid in people_ids:
            try:
                p = directus_get(f"/items/people/{pid}")
                people_names.append(p.get('data', {}).get('name', ''))
            except:
                pass
        
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
            # Use category-specific prompt with keyword replacement
            generation_prompt = category_prompt.format(
                title=title,
                source_url=source_url,
                movie_titles=', '.join(movie_titles) if movie_titles else 'None',
                people_names=', '.join(people_names) if people_names else 'None',
                category_name=category_name,
                research_context=research_context[:2000]
            )
            logger.info("Using category-specific prompt from Directus")
        else:
            # Fallback to default prompt
            logger.warning("No category prompt found, using default")
            generation_prompt = f"""Generate a comprehensive article based on this news.

ORIGINAL HEADLINE: {title}
SOURCE: {source_url}

MOVIES: {', '.join(movie_titles) if movie_titles else 'None'}
PEOPLE: {', '.join(people_names) if people_names else 'None'}
CATEGORY: {category_name}

RESEARCH CONTEXT:
{research_context[:2000]}

GENERATE 800-1000 word article with:
- Engaging introduction
- Detailed body with facts from research
- Quotes if available
- Analysis and context
- Conclusion
- FAQ section (4-5 questions)

For REVIEW category: Include rating, pros/cons, verdict
For NEWS category: Latest updates, industry impact
For OTT category: Platform details, release info, what to expect

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
        
        # STAGE 4: Image Generation
        image_uuid = stage_image_generation(title, seo_data.get('content', ''))
        
        # Extract rating/punchline for reviews
        rating = None
        rating_out_of = None
        source_name = None
        punchline = None
        
        if category_name.lower() == 'review':
            rating_match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+)', humanized)
            if rating_match:
                rating = float(rating_match.group(1))
                rating_out_of = int(rating_match.group(2))
            
            lines = humanized.split('\n')
            for line in lines[:10]:
                if len(line) > 20 and len(line) < 150:
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
        
        if source_name:
            article_data['source_name'] = source_name
        
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