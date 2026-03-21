"""
settings_server.py - Settings UI backend API
Runs: gunicorn -w 1 -b 0.0.0.0:3000 settings_server:app
"""

from flask import Flask, request, jsonify, send_from_directory
from common import *
import os

app = Flask(__name__, 
    static_folder='static',
    template_folder='templates'
)

# Serve static files
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# Serve settings page
@app.route('/')
@app.route('/settings')
def settings_page():
    return send_from_directory('templates', 'settings.html')

# ============================================================================
# SYSTEM SETTINGS
# ============================================================================

@app.route('/api/settings/system', methods=['GET'])
def get_system_settings():
    return jsonify({
        'directus_url': get_setting('directus_url', 'https://admin.gadgeek.in'),
        'directus_token': get_setting('directus_token', ''),
        'slack_bot_token': get_setting('slack_bot_token', ''),
        'slack_channel_id': get_setting('slack_channel_id', ''),
        'openrouter_api_key': get_setting('openrouter_api_key', ''),
        'tavily_api_key': get_setting('tavily_api_key', '')
    })

@app.route('/api/settings/system', methods=['POST'])
def save_system_settings():
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    return jsonify({'success': True})

# ============================================================================
# RSS FEEDS
# ============================================================================

@app.route('/api/settings/rss_feeds/news', methods=['GET'])
def get_news_feeds():
    return jsonify({'feeds': get_setting('news_rss_feeds', [])})

@app.route('/api/settings/rss_feeds/box_office', methods=['GET'])
def get_box_office_feeds():
    return jsonify({'feeds': get_setting('box_office_rss_feeds', [])})

@app.route('/api/settings/rss_feeds/news/add', methods=['POST'])
def add_news_feed():
    url = request.json.get('url')
    feeds = get_setting('news_rss_feeds', [])
    feeds.append({'url': url, 'enabled': True})
    set_setting('news_rss_feeds', feeds)
    return jsonify({'success': True})

@app.route('/api/settings/rss_feeds/box_office/add', methods=['POST'])
def add_box_office_feed():
    url = request.json.get('url')
    feeds = get_setting('box_office_rss_feeds', [])
    feeds.append({'url': url, 'enabled': True})
    set_setting('box_office_rss_feeds', feeds)
    return jsonify({'success': True})

@app.route('/api/settings/rss_feeds/news/toggle', methods=['POST'])
def toggle_news_feed():
    index = request.json.get('index')
    feeds = get_setting('news_rss_feeds', [])
    if 0 <= index < len(feeds):
        feeds[index]['enabled'] = not feeds[index].get('enabled', True)
        set_setting('news_rss_feeds', feeds)
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/settings/rss_feeds/box_office/toggle', methods=['POST'])
def toggle_box_office_feed():
    index = request.json.get('index')
    feeds = get_setting('box_office_rss_feeds', [])
    if 0 <= index < len(feeds):
        feeds[index]['enabled'] = not feeds[index].get('enabled', True)
        set_setting('box_office_rss_feeds', feeds)
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/settings/rss_feeds/news/remove', methods=['POST'])
def remove_news_feed():
    index = request.json.get('index')
    feeds = get_setting('news_rss_feeds', [])
    if 0 <= index < len(feeds):
        feeds.pop(index)
        set_setting('news_rss_feeds', feeds)
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/settings/rss_feeds/box_office/remove', methods=['POST'])
def remove_box_office_feed():
    index = request.json.get('index')
    feeds = get_setting('box_office_rss_feeds', [])
    if 0 <= index < len(feeds):
        feeds.pop(index)
        set_setting('box_office_rss_feeds', feeds)
        return jsonify({'success': True})
    return jsonify({'success': False})

# ============================================================================
# AI MODELS
# ============================================================================

@app.route('/api/settings/ai_models', methods=['GET'])
def get_ai_models():
    return jsonify({
        # Budget
        'budget_model': get_setting('budget_model', 'openai/gpt-4o-mini'),
        'budget_temperature': get_setting('budget_temperature', 0.3),
        'budget_max_tokens': get_setting('budget_max_tokens', 500),
        
        # News Articles (5 stages)
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
        
        # Daily Pages (3 stages)
        'daily_generation_model': get_setting('daily_generation_model', 'anthropic/claude-3.5-sonnet'),
        'daily_generation_temperature': get_setting('daily_generation_temperature', 0.7),
        'daily_generation_max_tokens': get_setting('daily_generation_max_tokens', 4000),
        'daily_humanize_model': get_setting('daily_humanize_model', 'anthropic/claude-3.5-sonnet'),
        'daily_humanize_temperature': get_setting('daily_humanize_temperature', 0.8),
        'daily_humanize_max_tokens': get_setting('daily_humanize_max_tokens', 4000),
        'daily_seo_model': get_setting('daily_seo_model', 'openai/gpt-4-turbo'),
        'daily_seo_temperature': get_setting('daily_seo_temperature', 0.5),
        'daily_seo_max_tokens': get_setting('daily_seo_max_tokens', 2000),
        
        # Hub Pages (2 stages)
        'hub_generation_model': get_setting('hub_generation_model', 'anthropic/claude-3.5-sonnet'),
        'hub_generation_temperature': get_setting('hub_generation_temperature', 0.7),
        'hub_generation_max_tokens': get_setting('hub_generation_max_tokens', 4000),
        'hub_seo_model': get_setting('hub_seo_model', 'openai/gpt-4-turbo'),
        'hub_seo_temperature': get_setting('hub_seo_temperature', 0.5),
        'hub_seo_max_tokens': get_setting('hub_seo_max_tokens', 2000),
        
        # Tavily
        'tavily_max_results': get_setting('tavily_max_results', 5)
    })

@app.route('/api/settings/ai_models', methods=['POST'])
def save_ai_models():
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    return jsonify({'success': True})

# ============================================================================
# SCRAPER
# ============================================================================

@app.route('/api/settings/scraper', methods=['GET'])
def get_scraper_settings():
    return jsonify({
        'scraper_interval_hours': get_setting('scraper_interval_hours', 4),
        'max_concurrent_scrapes': get_setting('max_concurrent_scrapes', 5),
        'scraper_proxies': get_setting('scraper_proxies', [])
    })

@app.route('/api/settings/scraper', methods=['POST'])
def save_scraper_settings():
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    return jsonify({'success': True})

# ============================================================================
# ADVANCED
# ============================================================================

@app.route('/api/settings/advanced', methods=['GET'])
def get_advanced_settings():
    return jsonify({
        'rss_check_interval_minutes': get_setting('rss_check_interval_minutes', 5),
        'fuzzy_match_threshold': get_setting('fuzzy_match_threshold', 90),
        'backfill_batch_size': get_setting('backfill_batch_size', 5),
        'backfill_delay_seconds': get_setting('backfill_delay_seconds', 120)
    })

@app.route('/api/settings/advanced', methods=['POST'])
def save_advanced_settings():
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    return jsonify({'success': True})

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=False)