# Box Office Automation System

Automated box office tracking and content generation system for Gadgeek.

## 📁 File Structure
```
/root/boxofficebot/
├── templates/
│   ├── settings.html
│   ├── settings.css
│   └── settings.js
├── config.py              # Redis configuration
├── common.py              # All shared utilities
├── scheduler.py           # All scheduled tasks
├── worker.py              # Content generation queue
├── server.py              # Slack + Settings UI
├── requirements.txt
└── README.md
```

## 🚀 Deployment on Coolify

### **Step 1: Install Dependencies**
```bash
cd /root/boxofficebot
pip install -r requirements.txt
playwright install chromium
playwright install-deps
```

### **Step 2: Environment Variables**

Set these in Coolify for all services:
```
REDIS_HOST=xs444swscgwwk48owwgow8oo
REDIS_PORT=6379
REDIS_DB=0
```

### **Step 3: Deploy Services**

#### **Service 1: Scheduler**
```yaml
Name: box-office-scheduler
Command: python -u scheduler.py
Port: None
Restart: Always
```

#### **Service 2: Worker**
```yaml
Name: box-office-worker
Command: python -u worker.py
Port: None
Restart: Always
```

#### **Service 3: Server**
```yaml
Name: box-office-server
Command: gunicorn -w 2 -b 0.0.0.0:8000 server:app
Port: 8000
Public Port: 8000
Domain: bot.gadgeek.in
Health Check: /health
Restart: Always
```

### **Step 4: Initialize Redis Settings**

Create and run `init_settings.py` once:
```python
import redis
import json

r = redis.Redis(host='xs444swscgwwk48owwgow8oo', port=6379, db=0, decode_responses=True)

settings = {
    # System
    'directus_url': 'https://admin.gadgeek.in',
    'directus_token': '',
    'slack_bot_token': 'xoxb-YOUR-TOKEN',
    'slack_channel_id': 'C01234567',
    'openrouter_api_key': 'sk-or-v1-YOUR-KEY',
    'tavily_api_key': 'tvly-YOUR-KEY',
    
    # RSS Feeds
    'news_rss_feeds': [],
    'box_office_rss_feeds': [],
    
    # Budget Model
    'budget_model': 'openai/gpt-4o-mini',
    'budget_temperature': 0.3,
    'budget_max_tokens': 500,
    
    # News Articles (5 stages)
    'news_generation_model': 'anthropic/claude-3.5-sonnet',
    'news_generation_temperature': 0.7,
    'news_generation_max_tokens': 8000,
    'news_humanize_model': 'anthropic/claude-3.5-sonnet',
    'news_humanize_temperature': 0.8,
    'news_humanize_max_tokens': 8000,
    'news_seo_model': 'openai/gpt-4-turbo',
    'news_seo_temperature': 0.5,
    'news_seo_max_tokens': 4000,
    'news_image_model': 'black-forest-labs/flux-schnell',
    'news_image_width': 1024,
    'news_image_height': 768,
    
    # Plot (2 stages)
    'plot_generation_model': 'anthropic/claude-3.5-sonnet',
    'plot_generation_temperature': 0.7,
    'plot_generation_max_tokens': 2000,
    'plot_humanize_model': 'anthropic/claude-3.5-sonnet',
    'plot_humanize_temperature': 0.8,
    'plot_humanize_max_tokens': 2000,
    
    # Daily Box Office (3 stages)
    'daily_generation_model': 'anthropic/claude-3.5-sonnet',
    'daily_generation_temperature': 0.7,
    'daily_generation_max_tokens': 4000,
    'daily_humanize_model': 'anthropic/claude-3.5-sonnet',
    'daily_humanize_temperature': 0.8,
    'daily_humanize_max_tokens': 4000,
    'daily_seo_model': 'openai/gpt-4-turbo',
    'daily_seo_temperature': 0.5,
    'daily_seo_max_tokens': 2000,
    
    # Hub (3 stages)
    'hub_generation_model': 'anthropic/claude-3.5-sonnet',
    'hub_generation_temperature': 0.7,
    'hub_generation_max_tokens': 4000,
    'hub_humanize_model': 'anthropic/claude-3.5-sonnet',
    'hub_humanize_temperature': 0.8,
    'hub_humanize_max_tokens': 4000,
    'hub_seo_model': 'openai/gpt-4-turbo',
    'hub_seo_temperature': 0.5,
    'hub_seo_max_tokens': 2000,
    
    # Fallback
    'fallback_generation_model': 'openai/gpt-4-turbo',
    
    # Tavily
    'tavily_max_results': 5,
    
    # Scraper
    'scraper_interval_hours': 4,
    'max_concurrent_scrapes': 5,
    'scraper_proxies': [],
    
    # Advanced
    'rss_check_interval_minutes': 5,
    'fuzzy_match_threshold': 90,
    'backfill_batch_size': 5,
    'backfill_delay_seconds': 120
}

for key, value in settings.items():
    r.set(f"settings:{key}", json.dumps(value))
    print(f"✅ Set {key}")

print("\n🎉 Settings initialized!")
```

Run: `python init_settings.py`

### **Step 5: Configure Directus**

Add `prompt_generation` field to `categories` collection:
```
Field Name: prompt_generation
Type: Text (Long)
Interface: Textarea
```

**Example Category Prompts:**

**News:**
```
Generate a news article about {title}.

MOVIES: {movie_titles}
PEOPLE: {people_names}

RESEARCH:
{research_context}

Write 800-word article with latest updates and industry impact.
```

**Review:**
```
Generate a movie review for {title}.

MOVIES: {movie_titles}
PEOPLE: {people_names}

RESEARCH:
{research_context}

Write 900-word review with:
- Plot summary (no spoilers)
- Performance analysis
- Rating out of 5
- Pros and cons
- Verdict
```

### **Step 6: Configure Slack**

1. Go to Slack App Settings → Interactivity & Shortcuts
2. Set Request URL: `https://bot.gadgeek.in/slack/interactions`

### **Step 7: Access Settings UI**

1. Open: `https://bot.gadgeek.in/settings`
2. Configure all settings
3. Add RSS feeds
4. Save

## ⏰ Service Schedule
```
scheduler.py:
  - 00:05 AM: Discovery + Transition + Daily Pages
  - 03:00 AM: Audit (correct estimates)
  - Every 4h: Scraper (live data + backfill)
  - Every 5m: RSS Monitor

worker.py:
  - 24/7: Process content generation queue

server.py:
  - 24/7: Slack webhooks + Settings UI
```

## 🔍 Monitoring

### **Check Logs:**
```bash
# Coolify UI → Service → Logs
# Or SSH:
docker logs -f box-office-scheduler
docker logs -f box-office-worker
docker logs -f box-office-server
```

### **Check Redis Queue:**
```bash
redis-cli -h xs444swscgwwk48owwgow8oo -p 6379
LLEN queue:content_generation
LRANGE queue:content_generation 0 -1
```

### **Check Settings:**
```bash
redis-cli -h xs444swscgwwk48owwgow8oo -p 6379
GET settings:news_generation_model
```

## 📊 AI Pipeline Stages

### **News Articles (5 stages):**
1. Tavily Research
2. Generation (with category prompt)
3. Humanization
4. SEO Optimization
5. Image Generation

### **Daily Box Office (3 stages):**
1. Generation
2. Humanization
3. SEO Optimization

### **Hub Pages (3 stages):**
1. Generation
2. Humanization
3. SEO Optimization

### **Movie Plot (2 stages):**
1. Generation
2. Humanization

## 🔗 Interlinking Features

- Movie names → Link to hub pages
- People names → Link to people pages
- "Day X" mentions → Link to day pages
- Related articles section (auto-generated)

## 🛠️ Troubleshooting

### **Scraper not working:**
```bash
# Install Playwright
pip install playwright
playwright install chromium
playwright install-deps
```

### **Queue jobs not processing:**
```bash
# Check worker logs
docker logs -f box-office-worker

# Check Redis queue
redis-cli -h xs444swscgwwk48owwgow8oo -p 6379
LLEN queue:content_generation
```

### **Settings not saving:**
```bash
# Check Redis connection
redis-cli -h xs444swscgwwk48owwgow8oo -p 6379
PING
```

## ✅ Deployment Checklist

- [ ] All 3 services deployed on Coolify
- [ ] Playwright installed on scheduler service
- [ ] Redis settings initialized
- [ ] Slack webhook URL configured
- [ ] Directus `prompt_generation` field added
- [ ] API keys added to settings UI
- [ ] RSS feeds added via settings UI
- [ ] Test Slack notification
- [ ] Verify queue processing
- [ ] Monitor for 24 hours

## 📝 Notes

- **Sacnilk HTML Selectors:** Update selectors in `common.py` (search for `# TODO`) based on actual HTML structure
- **Scraper Proxies:** Optional, leave empty for direct connection
- **Directus Token:** Optional if Public Access enabled on all collections
- **Failed Jobs:** Auto-retry during next scraper run

## 🎉 System Ready!

Your box office automation system is now live and ready to track movies, generate content, and publish automatically!
```

---

## ✅ **ALL FILES COMPLETE!**

---

## 📋 **FINAL FILE SUMMARY**

| # | File | Lines | Purpose |
|---|------|-------|---------|
| 1 | `config.py` | 10 | Redis config |
| 2 | `common.py` | ~800 | All shared code |
| 3 | `scheduler.py` | ~700 | All scheduled tasks |
| 4 | `worker.py` | ~300 | Queue processor |
| 5 | `server.py` | ~400 | Slack + Settings API |
| 6 | `settings.html` | ~450 | Settings UI |
| 7 | `settings.css` | ~250 | UI styles |
| 8 | `settings.js` | ~400 | UI logic |
| 9 | `requirements.txt` | 15 | Dependencies |
| 10 | `README.md` | ~400 | Deployment guide |

**Total: 10 files, ~3,725 lines of optimized code**

---

## 🎯 **3-SERVICE ARCHITECTURE**
```
Service 1: scheduler.py  → All scheduled automation
Service 2: worker.py     → Content generation queue
Service 3: server.py     → Slack + Settings UI