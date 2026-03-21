"""
server.py - Web layer for Slack webhooks + Settings UI
Runs on port 8000
"""

from flask import Flask, request, jsonify, send_from_directory, Response
from functools import wraps
from common import *
import json
import os

app = Flask(__name__, static_folder='templates', template_folder='templates')

# ============================================================================
# AUTHENTICATION
# ============================================================================

def check_auth(username, password):
    """Check if username/password is valid"""
    admin_username = get_setting('admin_username', 'admin')
    admin_password = get_setting('admin_password', 'boxoffice2024')
    
    return username == admin_username and password == admin_password

def authenticate():
    """Send 401 response for authentication"""
    return Response(
        'Authentication required.\nPlease login with your credentials.',
        401,
        {'WWW-Authenticate': 'Basic realm="Box Office Settings"'}
    )

def requires_auth(f):
    """Decorator for routes that require authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# ============================================================================
# SLACK WEBHOOK HANDLER (PUBLIC - NO AUTH)
# ============================================================================

def parse_slack_payload(payload: Dict) -> Optional[Dict]:
    """Parse Slack interaction payload"""
    try:
        action_id = payload.get('actions', [{}])[0].get('action_id')
        lead_id = payload.get('actions', [{}])[0].get('value')
        response_url = payload.get('response_url')
        channel = payload.get('container', {}).get('channel_id') or payload.get('channel', {}).get('id')
        message_ts = payload.get('container', {}).get('message_ts') or payload.get('message', {}).get('ts')
        
        state = payload.get('state', {}).get('values', {})
        
        movie_ids = []
        movies_block = state.get('movies_block', {})
        if movies_block:
            selected = movies_block.get('select_movies', {}).get('selected_options', [])
            movie_ids = [opt['value'] for opt in selected]
        
        people_ids = []
        people_block = state.get('people_block', {})
        if people_block:
            selected = people_block.get('select_people', {}).get('selected_options', [])
            people_ids = [opt['value'] for opt in selected]
        
        category_id = None
        category_block = state.get('category_block', {})
        if category_block:
            selected = category_block.get('select_category', {}).get('selected_option')
            if selected:
                category_id = selected.get('value')
        
        return {
            'action': action_id,
            'lead_id': lead_id,
            'movie_ids': movie_ids,
            'people_ids': people_ids,
            'category_id': category_id,
            'response_url': response_url,
            'channel': channel,
            'message_ts': message_ts
        }
        
    except Exception as e:
        logger.error(f"Parse Slack payload error: {e}")
        return None


@app.route('/slack/interactions', methods=['POST'])
def slack_interactions():
    """Handle Slack interactions (Approve/Reject) - PUBLIC"""
    try:
        payload_str = request.form.get('payload')
        if not payload_str:
            return jsonify({"error": "No payload"}), 400
        
        payload = json.loads(payload_str)
        parsed = parse_slack_payload(payload)
        
        if not parsed:
            return jsonify({"error": "Invalid payload"}), 400
        
        action = parsed.get('action')
        lead_id = parsed.get('lead_id')
        response_url = parsed.get('response_url')
        channel = parsed.get('channel')
        message_ts = parsed.get('message_ts')
        
        logger.info(f"Slack action: {action}, Lead: {lead_id}")
        
        # REJECT
        if action == 'reject_article':
            directus_patch(f"/items/news_leads/{lead_id}", {'status': 'rejected'})
            
            if channel and message_ts:
                slack_delete_message(channel, message_ts)
            
            if response_url:
                slack_ephemeral(response_url, "❌ Article rejected")
            
            return jsonify({"ok": True}), 200
        
        # APPROVE
        elif action == 'approve_article':
            movie_ids = parsed.get('movie_ids', [])
            people_ids = parsed.get('people_ids', [])
            category_id = parsed.get('category_id')
            
            if not movie_ids and not people_ids:
                if response_url:
                    slack_ephemeral(response_url, "⚠️ Select at least one movie or person")
                return jsonify({"error": "No selection"}), 200
            
            if not category_id:
                if response_url:
                    slack_ephemeral(response_url, "⚠️ Please select a category")
                return jsonify({"error": "No category"}), 200
            
            directus_patch(f"/items/news_leads/{lead_id}", {'status': 'approved_high'})
            
            job_data = {
                'type': 'news_article',
                'lead_id': lead_id,
                'movie_ids': movie_ids,
                'people_ids': people_ids,
                'category_id': category_id,
                'response_url': response_url
            }
            
            enqueue_job('queue:content_generation', job_data)
            
            if channel and message_ts:
                slack_delete_message(channel, message_ts)
            
            if response_url:
                slack_ephemeral(response_url, "✅ Article approved! Generating content...")
            
            return jsonify({"ok": True}), 200
        
        else:
            return jsonify({"error": "Unknown action"}), 400
        
    except Exception as e:
        logger.error(f"Slack webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# SETTINGS UI (PROTECTED)
# ============================================================================

@app.route('/')
@app.route('/settings')
@requires_auth
def settings_page():
    """Serve settings HTML page"""
    return send_from_directory('templates', 'settings.html')


@app.route('/static/<path:filename>')
@requires_auth
def serve_static(filename):
    """Serve static files (CSS/JS)"""
    return send_from_directory('templates', filename)

# ============================================================================
# SETTINGS API - SYSTEM (PROTECTED)
# ============================================================================

@app.route('/api/settings/system', methods=['GET'])
@requires_auth
def get_system_settings():
    """Get system settings"""
    return jsonify({
        'directus_url': get_setting('directus_url', 'https://admin.boxofficetalk.com'),
        'directus_token': get_setting('directus_token', ''),
        'slack_bot_token': get_setting('slack_bot_token', ''),
        'slack_channel_id': get_setting('slack_channel_id', ''),
        'openrouter_api_key': get_setting('openrouter_api_key', ''),
        'tavily_api_key': get_setting('tavily_api_key', ''),
        'admin_username': get_setting('admin_username', 'admin'),
        'admin_password': get_setting('admin_password', 'boxoffice2024')
    })


@app.route('/api/settings/system', methods=['POST'])
@requires_auth
def save_system_settings():
    """Save system settings"""
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    return jsonify({'success': True})

# ============================================================================
# SETTINGS API - RSS FEEDS (PROTECTED)
# ============================================================================

@app.route('/api/settings/rss_feeds/news', methods=['GET'])
@requires_auth
def get_news_feeds():
    """Get news RSS feeds"""
    return jsonify({'feeds': get_setting('news_rss_feeds', [])})


@app.route('/api/settings/rss_feeds/box_office', methods=['GET'])
@requires_auth
def get_box_office_feeds():
    """Get box office RSS feeds"""
    return jsonify({'feeds': get_setting('box_office_rss_feeds', [])})


@app.route('/api/settings/rss_feeds/news/add', methods=['POST'])
@requires_auth
def add_news_feed():
    """Add news RSS feed"""
    url = request.json.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'URL required'})
    
    feeds = get_setting('news_rss_feeds', [])
    feeds.append({'url': url, 'enabled': True})
    set_setting('news_rss_feeds', feeds)
    return jsonify({'success': True})


@app.route('/api/settings/rss_feeds/box_office/add', methods=['POST'])
@requires_auth
def add_box_office_feed():
    """Add box office RSS feed"""
    url = request.json.get('url')
    if not url:
        return jsonify({'success': False})
    
    feeds = get_setting('box_office_rss_feeds', [])
    feeds.append({'url': url, 'enabled': True})
    set_setting('box_office_rss_feeds', feeds)
    return jsonify({'success': True})


@app.route('/api/settings/rss_feeds/news/toggle', methods=['POST'])
@requires_auth
def toggle_news_feed():
    """Toggle news feed"""
    index = request.json.get('index')
    feeds = get_setting('news_rss_feeds', [])
    
    if 0 <= index < len(feeds):
        feeds[index]['enabled'] = not feeds[index].get('enabled', True)
        set_setting('news_rss_feeds', feeds)
        return jsonify({'success': True})
    
    return jsonify({'success': False})


@app.route('/api/settings/rss_feeds/box_office/toggle', methods=['POST'])
@requires_auth
def toggle_box_office_feed():
    """Toggle box office feed"""
    index = request.json.get('index')
    feeds = get_setting('box_office_rss_feeds', [])
    
    if 0 <= index < len(feeds):
        feeds[index]['enabled'] = not feeds[index].get('enabled', True)
        set_setting('box_office_rss_feeds', feeds)
        return jsonify({'success': True})
    
    return jsonify({'success': False})


@app.route('/api/settings/rss_feeds/news/remove', methods=['POST'])
@requires_auth
def remove_news_feed():
    """Remove news feed"""
    index = request.json.get('index')
    feeds = get_setting('news_rss_feeds', [])
    
    if 0 <= index < len(feeds):
        feeds.pop(index)
        set_setting('news_rss_feeds', feeds)
        return jsonify({'success': True})
    
    return jsonify({'success': False})


@app.route('/api/settings/rss_feeds/box_office/remove', methods=['POST'])
@requires_auth
def remove_box_office_feed():
    """Remove box office feed"""
    index = request.json.get('index')
    feeds = get_setting('box_office_rss_feeds', [])
    
    if 0 <= index < len(feeds):
        feeds.pop(index)
        set_setting('box_office_rss_feeds', feeds)
        return jsonify({'success': True})
    
    return jsonify({'success': False})

# ============================================================================
# SETTINGS API - AI MODELS (PROTECTED)
# ============================================================================

@app.route('/api/settings/ai_models', methods=['GET'])
@requires_auth
def get_ai_models():
    """Get AI model settings"""
    return jsonify({
        # Budget
        'budget_model': get_setting('budget_model', 'openai/gpt-4o-mini'),
        'budget_temperature': get_setting('budget_temperature', 0.3),
        'budget_max_tokens': get_setting('budget_max_tokens', 500),
        
        # News (5 stages)
        'news_generation_model': get_setting('news_generation_model', 'anthropic/claude-3.5-sonnet'),
        'news_generation_temperature': get_setting('news_generation_temperature', 0.7),
        'news_generation_max_tokens': get_setting('news_generation_max_tokens', 8000),
        'news_humanize_model': get_setting('news_humanize_model', 'anthropic/claude-3.5-sonnet'),
        'news_humanize_temperature': get_setting('news_humanize_temperature', 0.8),
        'news_humanize_max_tokens': get_setting('news_humanize_max_tokens', 8000),
        'news_seo_model': get_setting('news_seo_model', 'openai/gpt-4-turbo'),
        'news_seo_temperature': get_setting('news_seo_temperature', 0.5),
        'news_seo_max_tokens': get_setting('news_seo_max_tokens', 4000),
        'news_image_model': get_setting('news_image_model', 'black-forest-labs/flux-schnell'),
        'news_image_width': get_setting('news_image_width', 1024),
        'news_image_height': get_setting('news_image_height', 768),
        
        # Plot (2 stages)
        'plot_generation_model': get_setting('plot_generation_model', 'anthropic/claude-3.5-sonnet'),
        'plot_generation_temperature': get_setting('plot_generation_temperature', 0.7),
        'plot_generation_max_tokens': get_setting('plot_generation_max_tokens', 2000),
        'plot_humanize_model': get_setting('plot_humanize_model', 'anthropic/claude-3.5-sonnet'),
        'plot_humanize_temperature': get_setting('plot_humanize_temperature', 0.8),
        'plot_humanize_max_tokens': get_setting('plot_humanize_max_tokens', 2000),
        
        # Daily (3 stages)
        'daily_generation_model': get_setting('daily_generation_model', 'anthropic/claude-3.5-sonnet'),
        'daily_generation_temperature': get_setting('daily_generation_temperature', 0.7),
        'daily_generation_max_tokens': get_setting('daily_generation_max_tokens', 4000),
        'daily_humanize_model': get_setting('daily_humanize_model', 'anthropic/claude-3.5-sonnet'),
        'daily_humanize_temperature': get_setting('daily_humanize_temperature', 0.8),
        'daily_humanize_max_tokens': get_setting('daily_humanize_max_tokens', 4000),
        'daily_seo_model': get_setting('daily_seo_model', 'openai/gpt-4-turbo'),
        'daily_seo_temperature': get_setting('daily_seo_temperature', 0.5),
        'daily_seo_max_tokens': get_setting('daily_seo_max_tokens', 2000),
        
        # Hub (3 stages)
        'hub_generation_model': get_setting('hub_generation_model', 'anthropic/claude-3.5-sonnet'),
        'hub_generation_temperature': get_setting('hub_generation_temperature', 0.7),
        'hub_generation_max_tokens': get_setting('hub_generation_max_tokens', 4000),
        'hub_humanize_model': get_setting('hub_humanize_model', 'anthropic/claude-3.5-sonnet'),
        'hub_humanize_temperature': get_setting('hub_humanize_temperature', 0.8),
        'hub_humanize_max_tokens': get_setting('hub_humanize_max_tokens', 4000),
        'hub_seo_model': get_setting('hub_seo_model', 'openai/gpt-4-turbo'),
        'hub_seo_temperature': get_setting('hub_seo_temperature', 0.5),
        'hub_seo_max_tokens': get_setting('hub_seo_max_tokens', 2000),
        
        # Fallback
        'fallback_generation_model': get_setting('fallback_generation_model', 'openai/gpt-4-turbo'),
        
        # Tavily
        'tavily_max_results': get_setting('tavily_max_results', 5)
    })


@app.route('/api/settings/ai_models', methods=['POST'])
@requires_auth
def save_ai_models():
    """Save AI model settings"""
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    return jsonify({'success': True})

# ============================================================================
# SETTINGS API - SCRAPER (PROTECTED)
# ============================================================================

@app.route('/api/settings/scraper', methods=['GET'])
@requires_auth
def get_scraper_settings():
    """Get scraper settings"""
    return jsonify({
        'scraper_interval_hours': get_setting('scraper_interval_hours', 4),
        'max_concurrent_scrapes': get_setting('max_concurrent_scrapes', 5),
        'scraper_proxies': get_setting('scraper_proxies', [])
    })


@app.route('/api/settings/scraper', methods=['POST'])
@requires_auth
def save_scraper_settings():
    """Save scraper settings"""
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    return jsonify({'success': True})

# ============================================================================
# SETTINGS API - ADVANCED (PROTECTED)
# ============================================================================

@app.route('/api/settings/advanced', methods=['GET'])
@requires_auth
def get_advanced_settings():
    """Get advanced settings"""
    return jsonify({
        'rss_check_interval_minutes': get_setting('rss_check_interval_minutes', 5),
        'fuzzy_match_threshold': get_setting('fuzzy_match_threshold', 90),
        'backfill_batch_size': get_setting('backfill_batch_size', 5),
        'backfill_delay_seconds': get_setting('backfill_delay_seconds', 120)
    })


@app.route('/api/settings/advanced', methods=['POST'])
@requires_auth
def save_advanced_settings():
    """Save advanced settings"""
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    return jsonify({'success': True})

# ============================================================================
# HEALTH CHECK (PUBLIC)
# ============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'box-office-server',
        'timestamp': datetime.now().isoformat()
    }), 200

# ============================================================================
# RUN SERVER
# ============================================================================

if __name__ == '__main__':
    logger.info("Starting server in development mode...")
    app.run(host='0.0.0.0', port=8000, debug=False)