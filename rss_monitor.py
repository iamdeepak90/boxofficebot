"""
rss_monitor.py - Monitor RSS feeds continuously with budget LLM pre-check
Runs: Continuously (checks every N minutes from settings)
"""

import sys
import os
from common import *
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import feedparser
import time
import hashlib


# ============================================================================
# RSS FEED PARSING
# ============================================================================

def parse_rss_feed(feed_url: str) -> List[Dict]:
    """
    Parse RSS feed and extract entries
    Returns: List of entries
    """
    try:
        logger.info(f"Parsing RSS feed: {feed_url}")
        
        feed = feedparser.parse(feed_url)
        
        if feed.bozo:
            logger.warning(f"Feed parsing warning: {feed.bozo_exception}")
        
        entries = []
        
        for entry in feed.entries:
            # Extract basic data
            entry_data = {
                'title': entry.get('title', ''),
                'link': entry.get('link', ''),
                'description': entry.get('description', '') or entry.get('summary', ''),
                'published': entry.get('published', ''),
                'content': ''
            }
            
            # Try to get full content
            if hasattr(entry, 'content'):
                entry_data['content'] = entry.content[0].value
            elif hasattr(entry, 'summary_detail'):
                entry_data['content'] = entry.summary_detail.value
            
            entries.append(entry_data)
        
        logger.info(f"Found {len(entries)} entries in feed")
        return entries
        
    except Exception as e:
        logger.error(f"RSS parsing failed for {feed_url}: {e}")
        return []


# ============================================================================
# BUDGET LLM PRE-CHECK (CONFIDENCE SCORING)
# ============================================================================

def get_active_movies_context() -> str:
    """
    Get list of active movies (last 2 months + upcoming)
    Returns: Formatted string for prompt
    """
    try:
        today = datetime.now().date()
        two_months_ago = (today - timedelta(days=60)).strftime('%Y-%m-%d')
        
        # Get movies
        result = directus_get(
            f"/items/movies?filter[_or][0][release_date][_gte]={two_months_ago}&filter[_or][1][release_date][_gte]={today.strftime('%Y-%m-%d')}&filter[_or][2][status][_eq]=running&limit=500&fields=id,title,release_date,status,language"
        )
        
        movies = result.get('data', [])
        
        # Format for prompt
        movie_list = []
        for m in movies:
            movie_list.append(f"- {m.get('title')} (id: {m.get('id')}, release: {m.get('release_date')}, status: {m.get('status')})")
        
        return "\n".join(movie_list)
        
    except Exception as e:
        logger.error(f"Error fetching movies context: {e}")
        return ""


def get_all_people_context() -> str:
    """
    Get list of all people in database
    Returns: Formatted string for prompt
    """
    try:
        result = directus_get("/items/people?limit=1000&fields=id,name")
        people = result.get('data', [])
        
        people_list = []
        for p in people:
            people_list.append(f"- {p.get('name')} (id: {p.get('id')})")
        
        return "\n".join(people_list)
        
    except Exception as e:
        logger.error(f"Error fetching people context: {e}")
        return ""


def budget_llm_precheck(entry: Dict, movies_context: str, people_context: str) -> Optional[Dict]:
    """
    Quick LLM check to determine relevance and confidence
    Returns: {confidence, movie_ids, people_ids, category, is_relevant}
    """
    try:
        model = get_setting("budget_model", "openai/gpt-4o-mini")
        temperature = get_setting("budget_temperature", 0.3)
        max_tokens = get_setting("budget_max_tokens", 500)
        
        title = entry.get('title', '')
        description = entry.get('description', '')[:200]  # First 200 chars
        
        prompt = f"""Analyze this entertainment news headline quickly.

HEADLINE: {title}

SNIPPET: {description}

AVAILABLE MOVIES (last 2 months + upcoming):
{movies_context}

AVAILABLE PEOPLE:
{people_context}

Determine:
1. Is this relevant entertainment news? (movies/people/box office)
2. Which movie(s) is it about? (if any)
3. Which people are mentioned? (if any)
4. Category: news, review, or ott
5. Your confidence (0-1)

Return ONLY JSON (no markdown):
{{
  "is_relevant": true/false,
  "confidence": 0.95,
  "movie_ids": ["uuid1", "uuid2"],
  "people_ids": ["uuid1", "uuid2"],
  "category": "news"
}}"""
        
        result = call_openrouter(model, prompt, temperature, max_tokens)
        
        if not result:
            logger.warning("Budget LLM returned empty response")
            return None
        
        # Parse JSON
        analysis = extract_json_from_text(result)
        
        if not analysis:
            logger.warning("Could not parse JSON from budget LLM")
            return None
        
        logger.info(f"Budget LLM analysis: relevance={analysis.get('is_relevant')}, confidence={analysis.get('confidence')}")
        
        return analysis
        
    except Exception as e:
        logger.error(f"Budget LLM pre-check failed: {e}")
        return None


# ============================================================================
# SLACK POSTING
# ============================================================================

def post_to_slack_for_approval(entry: Dict, lead_id: str, analysis: Optional[Dict]):
    """
    Post RSS entry to Slack with dropdowns
    Pre-select based on confidence if available
    """
    try:
        title = entry.get('title', 'No title')
        source_url = entry.get('link', '')
        description = entry.get('description', '')[:200]
        
        # Get all movies and people for dropdowns
        movies_result = directus_get(
            f"/items/movies?filter[_or][0][release_date][_gte]={(datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')}&filter[_or][1][status][_eq]=running&limit=500&fields=id,title"
        )
        movies = movies_result.get('data', [])
        
        people_result = directus_get("/items/people?limit=500&fields=id,name")
        people = people_result.get('data', [])
        
        categories_result = directus_get("/items/categories?limit=100&fields=id,name")
        categories = categories_result.get('data', [])
        
        # Build movie options
        movie_options = []
        for m in movies:
            movie_options.append({
                "text": {"type": "plain_text", "text": m.get('title', '')[:75]},
                "value": m.get('id')
            })
        
        # Build people options
        people_options = []
        for p in people:
            people_options.append({
                "text": {"type": "plain_text", "text": p.get('name', '')[:75]},
                "value": p.get('id')
            })
        
        # Build category options
        category_options = []
        for c in categories:
            # Skip box_office category (not for RSS articles)
            if c.get('name', '').lower() == 'box office':
                continue
            category_options.append({
                "text": {"type": "plain_text", "text": c.get('name', '')},
                "value": c.get('id')
            })
        
        # Determine confidence badge
        confidence_badge = "⚪ No AI Check"
        confidence_color = "gray"
        
        if analysis:
            confidence = analysis.get('confidence', 0)
            if confidence >= 0.85:
                confidence_badge = f"🟢 AI Confidence: {int(confidence * 100)}%"
                confidence_color = "green"
            elif confidence >= 0.50:
                confidence_badge = f"🟡 AI Confidence: {int(confidence * 100)}%"
                confidence_color = "yellow"
            else:
                confidence_badge = f"🔴 AI Confidence: {int(confidence * 100)}%"
                confidence_color = "red"
        
        # Build initial values for pre-selection
        initial_movies = []
        initial_people = []
        initial_category = None
        
        if analysis and analysis.get('confidence', 0) >= 0.85:
            # High confidence - pre-select
            initial_movies = analysis.get('movie_ids', [])
            initial_people = analysis.get('people_ids', [])
            # Find category ID by name
            for c in categories:
                if c.get('name', '').lower() == analysis.get('category', '').lower():
                    initial_category = c.get('id')
                    break
        
        # Build Slack blocks
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📰 NEW ARTICLE LEAD"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{confidence_badge}*"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Headline:*\n{title}\n\n*Snippet:*\n{description}..."
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Source:* {source_url}"
                }
            }
        ]
        
        # Movies dropdown (multi-select)
        movie_block = {
            "type": "input",
            "block_id": "movies_block",
            "optional": True,
            "element": {
                "type": "multi_static_select",
                "action_id": "select_movies",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select movies (optional)"
                },
                "options": movie_options[:100]  # Slack limit
            },
            "label": {
                "type": "plain_text",
                "text": "🎬 Movies"
            }
        }
        
        # Add initial selection if high confidence
        if initial_movies:
            movie_block["element"]["initial_options"] = [
                {"text": {"type": "plain_text", "text": next((m['title'] for m in movies if m['id'] == mid), mid)[:75]}, "value": mid}
                for mid in initial_movies[:5]
                if any(m['id'] == mid for m in movies)
            ]
        
        blocks.append(movie_block)
        
        # People dropdown (multi-select)
        people_block = {
            "type": "input",
            "block_id": "people_block",
            "optional": True,
            "element": {
                "type": "multi_static_select",
                "action_id": "select_people",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select people (optional)"
                },
                "options": people_options[:100]  # Slack limit
            },
            "label": {
                "type": "plain_text",
                "text": "👥 People"
            }
        }
        
        # Add initial selection if high confidence
        if initial_people:
            people_block["element"]["initial_options"] = [
                {"text": {"type": "plain_text", "text": next((p['name'] for p in people if p['id'] == pid), pid)[:75]}, "value": pid}
                for pid in initial_people[:5]
                if any(p['id'] == pid for p in people)
            ]
        
        blocks.append(people_block)
        
        # Category dropdown (single-select)
        category_block = {
            "type": "input",
            "block_id": "category_block",
            "element": {
                "type": "static_select",
                "action_id": "select_category",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select category"
                },
                "options": category_options
            },
            "label": {
                "type": "plain_text",
                "text": "📁 Category"
            }
        }
        
        # Add initial selection if high confidence
        if initial_category:
            category_block["element"]["initial_option"] = {
                "text": {"type": "plain_text", "text": next((c['name'] for c in categories if c['id'] == initial_category), '')},
                "value": initial_category
            }
        
        blocks.append(category_block)
        
        # Action buttons
        blocks.append({
            "type": "actions",
            "block_id": "actions_block",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve & Generate"},
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
        })
        
        # Post to Slack
        result = slack_post_message(blocks, f"New article: {title}")
        
        if result:
            logger.info("✅ Posted to Slack successfully")
            return result
        else:
            logger.error("Failed to post to Slack")
            return None
            
    except Exception as e:
        logger.error(f"Slack posting failed: {e}")
        return None


# ============================================================================
# MAIN RSS MONITOR WORKFLOW
# ============================================================================

def process_rss_feeds():
    """
    Process all enabled RSS feeds
    """
    logger.info("=" * 60)
    logger.info("RSS FEED CHECK")
    logger.info("=" * 60)
    
    try:
        # Get RSS feeds from Redis
        feeds = get_setting("box_office_rss_feeds", [])
        
        if not feeds:
            logger.info("No RSS feeds configured")
            return
        
        logger.info(f"Checking {len(feeds)} RSS feeds")
        
        # Get context once (reuse for all entries)
        movies_context = get_active_movies_context()
        people_context = get_all_people_context()
        
        processed_count = 0
        skipped_count = 0
        
        for feed_config in feeds:
            if not feed_config.get('enabled', True):
                continue
            
            feed_url = feed_config.get('url')
            
            logger.info(f"\n{'=' * 40}")
            logger.info(f"Processing feed: {feed_url}")
            logger.info(f"{'=' * 40}")
            
            # Parse feed
            entries = parse_rss_feed(feed_url)
            
            for entry in entries:
                try:
                    source_url = entry.get('link', '')
                    
                    if not source_url:
                        logger.warning("Entry has no URL, skipping")
                        continue
                    
                    # Check if already processed
                    existing = directus_get(
                        f"/items/news_leads?filter[source_url][_eq]={source_url}&limit=1"
                    )
                    
                    if existing.get('data') and len(existing['data']) > 0:
                        logger.debug(f"Already processed: {source_url}")
                        skipped_count += 1
                        continue
                    
                    logger.info(f"\nNew entry: {entry.get('title', '')[:50]}...")
                    
                    # Budget LLM pre-check
                    analysis = budget_llm_precheck(entry, movies_context, people_context)
                    
                    # Filter by relevance
                    if analysis and not analysis.get('is_relevant', True):
                        logger.info("❌ Not relevant entertainment news, skipping")
                        skipped_count += 1
                        continue
                    
                    # Create news_leads entry
                    lead_data = {
                        'title': entry.get('title', ''),
                        'source_url': source_url,
                        'status': 'pending'
                    }
                    
                    result = directus_post('/items/news_leads', lead_data)
                    lead_id = result.get('data', {}).get('id')
                    
                    if not lead_id:
                        logger.error("Failed to create news lead")
                        continue
                    
                    logger.info(f"✅ Lead created: {lead_id}")
                    
                    # Post to Slack
                    post_to_slack_for_approval(entry, lead_id, analysis)
                    
                    processed_count += 1
                    
                    # Rate limiting
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error processing entry: {e}")
                    continue
            
            # Delay between feeds
            time.sleep(2)
        
        logger.info(f"\nRSS check complete:")
        logger.info(f"  - Processed: {processed_count} new entries")
        logger.info(f"  - Skipped: {skipped_count} entries")
        
    except Exception as e:
        logger.error(f"RSS monitor workflow failed: {e}")
    
    logger.info("=" * 60)


# ============================================================================
# CONTINUOUS DAEMON
# ============================================================================

if __name__ == "__main__":
    logger.info("RSS Monitor started")
    logger.info("=" * 60)
    
    # Get check interval from settings (default 5 minutes)
    check_interval = get_setting("rss_check_interval_minutes", 5)
    logger.info(f"Check interval: {check_interval} minutes")
    
    while True:
        try:
            process_rss_feeds()
            
            logger.info(f"\nSleeping for {check_interval} minutes...")
            time.sleep(check_interval * 60)
            
        except KeyboardInterrupt:
            logger.info("\nShutting down RSS monitor...")
            break
        except Exception as e:
            logger.error(f"Fatal error in RSS monitor: {e}")
            logger.info("Restarting in 1 minute...")
            time.sleep(60)