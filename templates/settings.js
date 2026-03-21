// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function showNotification(message, type = 'success') {
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = `notification ${type} show`;
    
    setTimeout(() => {
        notification.classList.remove('show');
    }, 3000);
}

function getInputValue(id) {
    const element = document.getElementById(id);
    return element ? element.value : '';
}

function setInputValue(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.value = value !== null && value !== undefined ? value : '';
    }
}

function safeParseJSON(str, defaultValue = []) {
    try {
        return JSON.parse(str);
    } catch (e) {
        return defaultValue;
    }
}

// ============================================================================
// TAB SWITCHING
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    const tabs = document.querySelectorAll('.tab');
    const panels = document.querySelectorAll('.panel');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const targetTab = this.dataset.tab;
            
            tabs.forEach(t => t.classList.remove('active'));
            panels.forEach(p => p.classList.remove('active'));
            
            this.classList.add('active');
            document.getElementById(targetTab).classList.add('active');
            
            if (targetTab === 'rss_feeds') {
                loadRSSFeeds();
            } else if (targetTab === 'ai_models') {
                loadAIModelsSettings();
            } else if (targetTab === 'system') {
                loadSystemSettings();
            } else if (targetTab === 'scraper') {
                loadScraperSettings();
            } else if (targetTab === 'advanced') {
                loadAdvancedSettings();
            }
        });
    });
    
    loadSystemSettings();
});

// ============================================================================
// SYSTEM SETTINGS
// ============================================================================

function loadSystemSettings() {
    fetch('/api/settings/system')
        .then(res => res.json())
        .then(data => {
            setInputValue('directus_url', data.directus_url);
            setInputValue('directus_token', data.directus_token);
            setInputValue('slack_bot_token', data.slack_bot_token);
            setInputValue('slack_channel_id', data.slack_channel_id);
            setInputValue('slack_signing_secret', data.slack_signing_secret);
            setInputValue('openrouter_api_key', data.openrouter_api_key);
            setInputValue('tavily_api_key', data.tavily_api_key);
        })
        .catch(err => {
            console.error('Error loading system settings:', err);
            showNotification('Error loading settings', 'error');
        });
}

function saveSystemSettings() {
    const settings = {
        directus_url: getInputValue('directus_url'),
        directus_token: getInputValue('directus_token'),
        slack_bot_token: getInputValue('slack_bot_token'),
        slack_channel_id: getInputValue('slack_channel_id'),
        slack_signing_secret: getInputValue('slack_signing_secret'),
        openrouter_api_key: getInputValue('openrouter_api_key'),
        tavily_api_key: getInputValue('tavily_api_key')
    };
    
    fetch('/api/settings/system', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showNotification('✅ System settings saved!', 'success');
            } else {
                showNotification('Error saving settings', 'error');
            }
        })
        .catch(err => {
            console.error('Error saving settings:', err);
            showNotification('Error saving settings', 'error');
        });
}

// ============================================================================
// RSS FEEDS
// ============================================================================

function loadRSSFeeds() {
    Promise.all([
        fetch('/api/settings/rss_feeds/news').then(r => r.json()),
        fetch('/api/settings/rss_feeds/box_office').then(r => r.json())
    ])
        .then(([newsData, boxOfficeData]) => {
            renderFeeds('news-feeds-list', newsData.feeds || []);
            renderFeeds('box-office-feeds-list', boxOfficeData.feeds || []);
        })
        .catch(err => {
            console.error('Error loading RSS feeds:', err);
            showNotification('Error loading RSS feeds', 'error');
        });
}

function renderFeeds(containerId, feeds) {
    const container = document.getElementById(containerId);
    
    if (!feeds || feeds.length === 0) {
        container.innerHTML = '<p class="no-data">No feeds configured</p>';
        return;
    }
    
    let html = '<div class="feeds-list">';
    
    feeds.forEach((feed, index) => {
        const enabled = feed.enabled !== false;
        html += `
            <div class="feed-item ${enabled ? 'enabled' : 'disabled'}">
                <div class="feed-url">${feed.url}</div>
                <div class="feed-actions">
                    <button onclick="toggleFeed('${containerId}', ${index})" class="btn-small btn-primary">
                        ${enabled ? '✓ Enabled' : '✗ Disabled'}
                    </button>
                    <button onclick="removeFeed('${containerId}', ${index})" class="btn-small btn-danger">
                        Remove
                    </button>
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    container.innerHTML = html;
}

function addNewsFeed() {
    const url = getInputValue('new_news_feed_url').trim();
    if (!url || !url.startsWith('http')) {
        showNotification('Invalid URL', 'error');
        return;
    }
    
    fetch('/api/settings/rss_feeds/news/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showNotification('Feed added', 'success');
                setInputValue('new_news_feed_url', '');
                loadRSSFeeds();
            } else {
                showNotification('Error adding feed', 'error');
            }
        });
}

function addBoxOfficeFeed() {
    const url = getInputValue('new_box_office_feed_url').trim();
    if (!url || !url.startsWith('http')) {
        showNotification('Invalid URL', 'error');
        return;
    }
    
    fetch('/api/settings/rss_feeds/box_office/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showNotification('Feed added', 'success');
                setInputValue('new_box_office_feed_url', '');
                loadRSSFeeds();
            } else {
                showNotification('Error adding feed', 'error');
            }
        });
}

function toggleFeed(containerId, index) {
    const feedType = containerId.includes('news') ? 'news' : 'box_office';
    
    fetch(`/api/settings/rss_feeds/${feedType}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index })
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                loadRSSFeeds();
            }
        });
}

function removeFeed(containerId, index) {
    if (!confirm('Remove this feed?')) return;
    
    const feedType = containerId.includes('news') ? 'news' : 'box_office';
    
    fetch(`/api/settings/rss_feeds/${feedType}/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index })
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showNotification('Feed removed', 'success');
                loadRSSFeeds();
            }
        });
}

// ============================================================================
// AI MODELS
// ============================================================================

function loadAIModelsSettings() {
    fetch('/api/settings/ai_models')
        .then(res => res.json())
        .then(data => {
            // Budget
            setInputValue('budget_model', data.budget_model);
            setInputValue('budget_temperature', data.budget_temperature);
            setInputValue('budget_max_tokens', data.budget_max_tokens);
            
            // News
            setInputValue('news_generation_model', data.news_generation_model);
            setInputValue('news_generation_temperature', data.news_generation_temperature);
            setInputValue('news_generation_max_tokens', data.news_generation_max_tokens);
            setInputValue('news_humanize_model', data.news_humanize_model);
            setInputValue('news_humanize_temperature', data.news_humanize_temperature);
            setInputValue('news_humanize_max_tokens', data.news_humanize_max_tokens);
            setInputValue('news_seo_model', data.news_seo_model);
            setInputValue('news_seo_temperature', data.news_seo_temperature);
            setInputValue('news_seo_max_tokens', data.news_seo_max_tokens);
            setInputValue('news_image_model', data.news_image_model);
            setInputValue('news_image_width', data.news_image_width);
            setInputValue('news_image_height', data.news_image_height);
            
            // Plot
            setInputValue('plot_generation_model', data.plot_generation_model);
            setInputValue('plot_generation_temperature', data.plot_generation_temperature);
            setInputValue('plot_generation_max_tokens', data.plot_generation_max_tokens);
            setInputValue('plot_humanize_model', data.plot_humanize_model);
            setInputValue('plot_humanize_temperature', data.plot_humanize_temperature);
            setInputValue('plot_humanize_max_tokens', data.plot_humanize_max_tokens);
            
            // Daily
            setInputValue('daily_generation_model', data.daily_generation_model);
            setInputValue('daily_generation_temperature', data.daily_generation_temperature);
            setInputValue('daily_generation_max_tokens', data.daily_generation_max_tokens);
            setInputValue('daily_humanize_model', data.daily_humanize_model);
            setInputValue('daily_humanize_temperature', data.daily_humanize_temperature);
            setInputValue('daily_humanize_max_tokens', data.daily_humanize_max_tokens);
            setInputValue('daily_seo_model', data.daily_seo_model);
            setInputValue('daily_seo_temperature', data.daily_seo_temperature);
            setInputValue('daily_seo_max_tokens', data.daily_seo_max_tokens);
            
            // Hub
            setInputValue('hub_generation_model', data.hub_generation_model);
            setInputValue('hub_generation_temperature', data.hub_generation_temperature);
            setInputValue('hub_generation_max_tokens', data.hub_generation_max_tokens);
            setInputValue('hub_humanize_model', data.hub_humanize_model);
            setInputValue('hub_humanize_temperature', data.hub_humanize_temperature);
            setInputValue('hub_humanize_max_tokens', data.hub_humanize_max_tokens);
            setInputValue('hub_seo_model', data.hub_seo_model);
            setInputValue('hub_seo_temperature', data.hub_seo_temperature);
            setInputValue('hub_seo_max_tokens', data.hub_seo_max_tokens);
            
            // Tavily
            setInputValue('tavily_max_results', data.tavily_max_results);
        })
        .catch(err => console.error('Error loading AI models:', err));
}

function saveAIModelsSettings() {
    const settings = {
        budget_model: getInputValue('budget_model'),
        budget_temperature: parseFloat(getInputValue('budget_temperature')),
        budget_max_tokens: parseInt(getInputValue('budget_max_tokens')),
        
        news_generation_model: getInputValue('news_generation_model'),
        news_generation_temperature: parseFloat(getInputValue('news_generation_temperature')),
        news_generation_max_tokens: parseInt(getInputValue('news_generation_max_tokens')),
        news_humanize_model: getInputValue('news_humanize_model'),
        news_humanize_temperature: parseFloat(getInputValue('news_humanize_temperature')),
        news_humanize_max_tokens: parseInt(getInputValue('news_humanize_max_tokens')),
        news_seo_model: getInputValue('news_seo_model'),
        news_seo_temperature: parseFloat(getInputValue('news_seo_temperature')),
        news_seo_max_tokens: parseInt(getInputValue('news_seo_max_tokens')),
        news_image_model: getInputValue('news_image_model'),
        news_image_width: parseInt(getInputValue('news_image_width')),
        news_image_height: parseInt(getInputValue('news_image_height')),
        
        plot_generation_model: getInputValue('plot_generation_model'),
        plot_generation_temperature: parseFloat(getInputValue('plot_generation_temperature')),
        plot_generation_max_tokens: parseInt(getInputValue('plot_generation_max_tokens')),
        plot_humanize_model: getInputValue('plot_humanize_model'),
        plot_humanize_temperature: parseFloat(getInputValue('plot_humanize_temperature')),
        plot_humanize_max_tokens: parseInt(getInputValue('plot_humanize_max_tokens')),
        
        daily_generation_model: getInputValue('daily_generation_model'),
        daily_generation_temperature: parseFloat(getInputValue('daily_generation_temperature')),
        daily_generation_max_tokens: parseInt(getInputValue('daily_generation_max_tokens')),
        daily_humanize_model: getInputValue('daily_humanize_model'),
        daily_humanize_temperature: parseFloat(getInputValue('daily_humanize_temperature')),
        daily_humanize_max_tokens: parseInt(getInputValue('daily_humanize_max_tokens')),
        daily_seo_model: getInputValue('daily_seo_model'),
        daily_seo_temperature: parseFloat(getInputValue('daily_seo_temperature')),
        daily_seo_max_tokens: parseInt(getInputValue('daily_seo_max_tokens')),
        
        hub_generation_model: getInputValue('hub_generation_model'),
        hub_generation_temperature: parseFloat(getInputValue('hub_generation_temperature')),
        hub_generation_max_tokens: parseInt(getInputValue('hub_generation_max_tokens')),
        hub_humanize_model: getInputValue('hub_humanize_model'),
        hub_humanize_temperature: parseFloat(getInputValue('hub_humanize_temperature')),
        hub_humanize_max_tokens: parseInt(getInputValue('hub_humanize_max_tokens')),
        hub_seo_model: getInputValue('hub_seo_model'),
        hub_seo_temperature: parseFloat(getInputValue('hub_seo_temperature')),
        hub_seo_max_tokens: parseInt(getInputValue('hub_seo_max_tokens')),
        
        tavily_max_results: parseInt(getInputValue('tavily_max_results'))
    };
    
    fetch('/api/settings/ai_models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showNotification('✅ AI models settings saved!', 'success');
            } else {
                showNotification('Error saving settings', 'error');
            }
        });
}

// ============================================================================
// SCRAPER SETTINGS
// ============================================================================

function loadScraperSettings() {
    fetch('/api/settings/scraper')
        .then(res => res.json())
        .then(data => {
            setInputValue('scraper_interval_hours', data.scraper_interval_hours);
            setInputValue('max_concurrent_scrapes', data.max_concurrent_scrapes);
            setInputValue('scraper_proxies', JSON.stringify(data.scraper_proxies || [], null, 2));
        })
        .catch(err => console.error('Error loading scraper settings:', err));
}

function saveScraperSettings() {
    const settings = {
        scraper_interval_hours: parseInt(getInputValue('scraper_interval_hours')),
        max_concurrent_scrapes: parseInt(getInputValue('max_concurrent_scrapes')),
        scraper_proxies: safeParseJSON(getInputValue('scraper_proxies'), [])
    };
    
    fetch('/api/settings/scraper', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showNotification('✅ Scraper settings saved!', 'success');
            } else {
                showNotification('Error saving settings', 'error');
            }
        });
}

// ============================================================================
// ADVANCED SETTINGS
// ============================================================================

function loadAdvancedSettings() {
    fetch('/api/settings/advanced')
        .then(res => res.json())
        .then(data => {
            setInputValue('rss_check_interval_minutes', data.rss_check_interval_minutes);
            setInputValue('fuzzy_match_threshold', data.fuzzy_match_threshold);
            setInputValue('backfill_batch_size', data.backfill_batch_size);
            setInputValue('backfill_delay_seconds', data.backfill_delay_seconds);
        })
        .catch(err => console.error('Error loading advanced settings:', err));
}

function saveAdvancedSettings() {
    const settings = {
        rss_check_interval_minutes: parseInt(getInputValue('rss_check_interval_minutes')),
        fuzzy_match_threshold: parseInt(getInputValue('fuzzy_match_threshold')),
        backfill_batch_size: parseInt(getInputValue('backfill_batch_size')),
        backfill_delay_seconds: parseInt(getInputValue('backfill_delay_seconds'))
    };
    
    fetch('/api/settings/advanced', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showNotification('✅ Advanced settings saved!', 'success');
            } else {
                showNotification('Error saving settings', 'error');
            }
        });
}