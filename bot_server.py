"""
bot_server.py - Flask server for Slack webhooks
Handles: Approve/Reject interactions, push to queue
Runs: gunicorn -w 1 -b 0.0.0.0:8000 bot_server:app
"""

import sys
import os
from flask import Flask, request, jsonify
from common import *
import json
from typing import Dict, Optional

app = Flask(__name__)


# ============================================================================
# SLACK INTERACTION PARSER
# ============================================================================

def parse_slack_payload(payload: Dict) -> Optional[Dict]:
    """
    Parse Slack interaction payload
    Returns: {action, lead_id, movie_ids, people_ids, category_id, response_url, channel, ts}
    """
    try:
        action_id = payload.get('actions', [{}])[0].get('action_id')
        lead_id = payload.get('actions', [{}])[0].get('value')
        
        # Get response_url for ephemeral messages
        response_url = payload.get('response_url')
        
        # Get channel and timestamp for message deletion
        channel = payload.get('container', {}).get('channel_id') or payload.get('channel', {}).get('id')
        message_ts = payload.get('container', {}).get('message_ts') or payload.get('message', {}).get('ts')
        
        # Extract selected values from state
        state = payload.get('state', {}).get('values', {})
        
        # Movies (multi-select)
        movie_ids = []
        movies_block = state.get('movies_block', {})
        if movies_block:
            selected_movies = movies_block.get('select_movies', {}).get('selected_options', [])
            movie_ids = [opt['value'] for opt in selected_movies]
        
        # People (multi-select)
        people_ids = []
        people_block = state.get('people_block', {})
        if people_block:
            selected_people = people_block.get('select_people', {}).get('selected_options', [])
            people_ids = [opt['value'] for opt in selected_people]
        
        # Category (single-select)
        category_id = None
        category_block = state.get('category_block', {})
        if category_block:
            selected_category = category_block.get('select_category', {}).get('selected_option')
            if selected_category:
                category_id = selected_category.get('value')
        
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
        logger.error(f"Error parsing Slack payload: {e}")
        return None


# ============================================================================
# VALIDATION
# ============================================================================

def validate_selections(parsed: Dict) -> tuple:
    """
    Validate user selections
    Returns: (is_valid, error_message)
    """
    movie_ids = parsed.get('movie_ids', [])
    people_ids = parsed.get('people_ids', [])
    category_id = parsed.get('category_id')
    
    # Must have at least one movie OR one person
    if not movie_ids and not people_ids:
        return False, "⚠️ Please select at least one movie or person"
    
    # Must have category (required for approve)
    if parsed.get('action') == 'approve_article' and not category_id:
        return False, "⚠️ Please select a category"
    
    return True, None


# ============================================================================
# SLACK WEBHOOK ENDPOINT
# ============================================================================

@app.route('/slack/interactions', methods=['POST'])
def slack_interactions():
    """Handle Slack interactive components"""
    try:
        # Parse payload
        payload_str = request.form.get('payload')
        if not payload_str:
            return jsonify({"error": "No payload"}), 400
        
        payload = json.loads(payload_str)
        
        logger.info("Received Slack interaction")
        
        # Parse interaction
        parsed = parse_slack_payload(payload)
        
        if not parsed:
            return jsonify({"error": "Invalid payload"}), 400
        
        action = parsed.get('action')
        lead_id = parsed.get('lead_id')
        response_url = parsed.get('response_url')
        channel = parsed.get('channel')
        message_ts = parsed.get('message_ts')
        
        logger.info(f"Action: {action}, Lead: {lead_id}")
        
        # ====================================================================
        # REJECT ACTION
        # ====================================================================
        
        if action == 'reject_article':
            try:
                # Update lead status
                directus_patch(f"/items/news_leads/{lead_id}", {
                    'status': 'rejected'
                })
                
                logger.info(f"Lead {lead_id} rejected")
                
                # Delete Slack message
                if channel and message_ts:
                    slack_delete_message(channel, message_ts)
                
                # Send ephemeral confirmation
                if response_url:
                    slack_ephemeral(response_url, "❌ Article rejected")
                
                return jsonify({"ok": True}), 200
                
            except Exception as e:
                logger.error(f"Reject action failed: {e}")
                if response_url:
                    slack_ephemeral(response_url, f"Error: {str(e)}")
                return jsonify({"error": str(e)}), 500
        
        # ====================================================================
        # APPROVE ACTION
        # ====================================================================
        
        elif action == 'approve_article':
            try:
                # Validate selections
                is_valid, error_msg = validate_selections(parsed)
                
                if not is_valid:
                    if response_url:
                        slack_ephemeral(response_url, error_msg)
                    return jsonify({"error": error_msg}), 200  # Return 200 to avoid Slack retry
                
                # Update lead status
                directus_patch(f"/items/news_leads/{lead_id}", {
                    'status': 'approved_high'
                })
                
                logger.info(f"Lead {lead_id} approved")
                
                # Build job data
                job_data = {
                    'type': 'news_article',
                    'lead_id': lead_id,
                    'movie_ids': parsed.get('movie_ids', []),
                    'people_ids': parsed.get('people_ids', []),
                    'category_id': parsed.get('category_id'),
                    'response_url': response_url
                }
                
                # Enqueue job
                enqueue_job('queue:content_generation', job_data)
                
                logger.info(f"Job enqueued for lead {lead_id}")
                
                # Delete Slack message
                if channel and message_ts:
                    slack_delete_message(channel, message_ts)
                
                # Send ephemeral confirmation
                if response_url:
                    slack_ephemeral(response_url, "✅ Article approved! Generating content...")
                
                return jsonify({"ok": True}), 200
                
            except Exception as e:
                logger.error(f"Approve action failed: {e}")
                if response_url:
                    slack_ephemeral(response_url, f"Error: {str(e)}")
                return jsonify({"error": str(e)}), 500
        
        # ====================================================================
        # UNKNOWN ACTION
        # ====================================================================
        
        else:
            logger.warning(f"Unknown action: {action}")
            return jsonify({"error": "Unknown action"}), 400
        
    except Exception as e:
        logger.error(f"Slack interaction handler error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "box-office-bot-server",
        "timestamp": datetime.now().isoformat()
    }), 200


@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({
        "service": "Box Office Bot Server",
        "status": "running",
        "endpoints": {
            "/slack/interactions": "POST - Slack webhook handler",
            "/health": "GET - Health check"
        }
    }), 200


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    # Development mode only
    # Use gunicorn in production
    logger.info("Starting bot server in development mode...")
    app.run(host='0.0.0.0', port=8000, debug=False)