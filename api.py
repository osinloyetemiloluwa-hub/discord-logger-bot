"""
Discord Logger API - Flask REST API
Query stored Discord messages via HTTP endpoints
"""

from flask import Flask, request, jsonify, g
from flask_cors import CORS
from datetime import datetime, timedelta
import os
import logging
from database import Message, Attachment, EditedMessage, DeletedMessage, SessionLocal, init_db

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_db():
    """Get database session"""
    if 'db' not in g:
        g.db = SessionLocal()
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Close database session after request"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


# ============ Health Check ============

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Discord Logger API',
        'timestamp': datetime.utcnow().isoformat()
    })


# ============ Messages API ============

@app.route('/api/messages', methods=['GET'])
def get_messages():
    """
    Get messages with optional filters

    Query Parameters:
    - channel_id: Filter by channel ID
    - guild_id: Filter by guild ID
    - author_id: Filter by author ID
    - limit: Max number of messages (default 100, max 1000)
    - offset: Pagination offset (default 0)
    - before: Get messages before this timestamp (ISO format)
    - after: Get messages after this timestamp (ISO format)
    - search: Search in message content
    """
    db = get_db()
    try:
        query = db.query(Message)

        # Apply filters
        if request.args.get('channel_id'):
            query = query.filter(Message.channel_id == request.args.get('channel_id'))

        if request.args.get('guild_id'):
            query = query.filter(Message.guild_id == request.args.get('guild_id'))

        if request.args.get('author_id'):
            query = query.filter(Message.author_id == request.args.get('author_id'))

        if request.args.get('search'):
            search_term = f"%{request.args.get('search')}%"
            query = query.filter(Message.content.like(search_term))

        if request.args.get('before'):
            before_date = datetime.fromisoformat(request.args.get('before').replace('Z', '+00:00'))
            query = query.filter(Message.timestamp < before_date)

        if request.args.get('after'):
            after_date = datetime.fromisoformat(request.args.get('after').replace('Z', '+00:00'))
            query = query.filter(Message.timestamp > after_date)

        # Order and paginate
        query = query.order_by(Message.timestamp.desc())
        limit = min(int(request.args.get('limit', 100)), 1000)
        offset = int(request.args.get('offset', 0))
        query = query.limit(limit).offset(offset)

        messages = query.all()

        return jsonify({
            'success': True,
            'count': len(messages),
            'limit': limit,
            'offset': offset,
            'messages': [msg.to_dict() for msg in messages]
        })

    except Exception as e:
        logger.error(f'Error fetching messages: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/messages/<message_id>', methods=['GET'])
def get_message(message_id):
    """Get a specific message by ID"""
    db = get_db()
    try:
        message = db.query(Message).filter_by(message_id=message_id).first()

        if not message:
            return jsonify({'success': False, 'error': 'Message not found'}), 404

        return jsonify({
            'success': True,
            'message': message.to_dict()
        })

    except Exception as e:
        logger.error(f'Error fetching message: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/messages/<message_id>/attachments', methods=['GET'])
def get_message_attachments(message_id):
    """Get all attachments for a specific message"""
    db = get_db()
    try:
        attachments = db.query(Attachment).filter_by(message_id=message_id).all()

        return jsonify({
            'success': True,
            'count': len(attachments),
            'attachments': [att.to_dict() for att in attachments]
        })

    except Exception as e:
        logger.error(f'Error fetching attachments: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/messages/<message_id>/edits', methods=['GET'])
def get_message_edits(message_id):
    """Get edit history for a specific message"""
    db = get_db()
    try:
        edits = db.query(EditedMessage).filter_by(message_id=message_id).order_by(EditedMessage.edited_at).all()

        return jsonify({
            'success': True,
            'count': len(edits),
            'edits': [edit.to_dict() for edit in edits]
        })

    except Exception as e:
        logger.error(f'Error fetching edits: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ Channels API ============

@app.route('/api/channels/<channel_id>/messages', methods=['GET'])
def get_channel_messages(channel_id):
    """
    Get all messages in a specific channel

    Query Parameters:
    - limit: Max number of messages (default 100, max 1000)
    - offset: Pagination offset (default 0)
    - before: Get messages before this timestamp
    - after: Get messages after this timestamp
    """
    db = get_db()
    try:
        query = db.query(Message).filter_by(channel_id=channel_id)

        if request.args.get('before'):
            before_date = datetime.fromisoformat(request.args.get('before').replace('Z', '+00:00'))
            query = query.filter(Message.timestamp < before_date)

        if request.args.get('after'):
            after_date = datetime.fromisoformat(request.args.get('after').replace('Z', '+00:00'))
            query = query.filter(Message.timestamp > after_date)

        query = query.order_by(Message.timestamp.desc())
        limit = min(int(request.args.get('limit', 100)), 1000)
        offset = int(request.args.get('offset', 0))
        query = query.limit(limit).offset(offset)

        messages = query.all()

        return jsonify({
            'success': True,
            'channel_id': channel_id,
            'count': len(messages),
            'messages': [msg.to_dict() for msg in messages]
        })

    except Exception as e:
        logger.error(f'Error fetching channel messages: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/channels', methods=['GET'])
def get_channels():
    """Get list of all channels with message counts"""
    db = get_db()
    try:
        from sqlalchemy import func

        channels = db.query(
            Message.channel_id,
            Message.channel_name,
            Message.guild_id,
            Message.guild_name,
            func.count(Message.id).label('message_count')
        ).group_by(
            Message.channel_id
        ).all()

        return jsonify({
            'success': True,
            'count': len(channels),
            'channels': [
                {
                    'channel_id': c.channel_id,
                    'channel_name': c.channel_name,
                    'guild_id': c.guild_id,
                    'guild_name': c.guild_name,
                    'message_count': c.message_count
                }
                for c in channels
            ]
        })

    except Exception as e:
        logger.error(f'Error fetching channels: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ Users/Authors API ============

@app.route('/api/users/<author_id>/messages', methods=['GET'])
def get_user_messages(author_id):
    """
    Get all messages from a specific user

    Query Parameters:
    - limit: Max number of messages (default 100, max 1000)
    - offset: Pagination offset (default 0)
    - guild_id: Filter by guild
    - channel_id: Filter by channel
    """
    db = get_db()
    try:
        query = db.query(Message).filter_by(author_id=author_id)

        if request.args.get('guild_id'):
            query = query.filter(Message.guild_id == request.args.get('guild_id'))

        if request.args.get('channel_id'):
            query = query.filter(Message.channel_id == request.args.get('channel_id'))

        query = query.order_by(Message.timestamp.desc())
        limit = min(int(request.args.get('limit', 100)), 1000)
        offset = int(request.args.get('offset', 0))
        query = query.limit(limit).offset(offset)

        messages = query.all()

        return jsonify({
            'success': True,
            'author_id': author_id,
            'count': len(messages),
            'messages': [msg.to_dict() for msg in messages]
        })

    except Exception as e:
        logger.error(f'Error fetching user messages: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/users', methods=['GET'])
def get_users():
    """Get list of all users with message counts"""
    db = get_db()
    try:
        from sqlalchemy import func

        users = db.query(
            Message.author_id,
            Message.author_name,
            func.count(Message.id).label('message_count')
        ).group_by(
            Message.author_id
        ).order_by(
            func.count(Message.id).desc()
        ).all()

        return jsonify({
            'success': True,
            'count': len(users),
            'users': [
                {
                    'author_id': u.author_id,
                    'author_name': u.author_name,
                    'message_count': u.message_count
                }
                for u in users
            ]
        })

    except Exception as e:
        logger.error(f'Error fetching users: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ Deleted Messages API ============

@app.route('/api/deleted', methods=['GET'])
def get_deleted_messages():
    """
    Get deleted messages

    Query Parameters:
    - channel_id: Filter by channel
    - guild_id: Filter by guild
    - limit: Max number (default 100, max 1000)
    - offset: Pagination offset
    """
    db = get_db()
    try:
        query = db.query(DeletedMessage)

        if request.args.get('channel_id'):
            query = query.filter(DeletedMessage.channel_id == request.args.get('channel_id'))

        if request.args.get('guild_id'):
            query = query.filter(DeletedMessage.guild_id == request.args.get('guild_id'))

        query = query.order_by(DeletedMessage.deleted_at.desc())
        limit = min(int(request.args.get('limit', 100)), 1000)
        offset = int(request.args.get('offset', 0))
        query = query.limit(limit).offset(offset)

        messages = query.all()

        return jsonify({
            'success': True,
            'count': len(messages),
            'deleted_messages': [msg.to_dict() for msg in messages]
        })

    except Exception as e:
        logger.error(f'Error fetching deleted messages: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/deleted/<message_id>', methods=['GET'])
def get_deleted_message(message_id):
    """Get a specific deleted message"""
    db = get_db()
    try:
        message = db.query(DeletedMessage).filter_by(message_id=message_id).first()

        if not message:
            return jsonify({'success': False, 'error': 'Deleted message not found'}), 404

        return jsonify({
            'success': True,
            'deleted_message': message.to_dict()
        })

    except Exception as e:
        logger.error(f'Error fetching deleted message: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ Statistics API ============

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get overall statistics"""
    db = get_db()
    try:
        from sqlalchemy import func

        total_messages = db.query(func.count(Message.id)).scalar()
        total_deleted = db.query(func.count(DeletedMessage.id)).scalar()
        total_edits = db.query(func.count(EditedMessage.id)).scalar()
        total_attachments = db.query(func.count(Attachment.id)).scalar()
        total_users = db.query(func.count(func.distinct(Message.author_id))).scalar()
        total_channels = db.query(func.count(func.distinct(Message.channel_id))).scalar()

        # Messages in last 7 days
        week_ago = datetime.utcnow() - timedelta(days=7)
        messages_this_week = db.query(func.count(Message.id)).filter(
            Message.timestamp >= week_ago
        ).scalar()

        return jsonify({
            'success': True,
            'stats': {
                'total_messages': total_messages,
                'total_deleted': total_deleted,
                'total_edits': total_edits,
                'total_attachments': total_attachments,
                'total_users': total_users,
                'total_channels': total_channels,
                'messages_this_week': messages_this_week,
                'generated_at': datetime.utcnow().isoformat()
            }
        })

    except Exception as e:
        logger.error(f'Error fetching stats: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/stats/activity', methods=['GET'])
def get_activity_stats():
    """
    Get message activity by day

    Query Parameters:
    - days: Number of days to look back (default 30, max 90)
    """
    db = get_db()
    try:
        from sqlalchemy import func

        days = min(int(request.args.get('days', 30)), 90)
        start_date = datetime.utcnow() - timedelta(days=days)

        # Group by date
        activity = db.query(
            func.date(Message.timestamp).label('date'),
            func.count(Message.id).label('count')
        ).filter(
            Message.timestamp >= start_date
        ).group_by(
            func.date(Message.timestamp)
        ).order_by(
            func.date(Message.timestamp)
        ).all()

        return jsonify({
            'success': True,
            'days': days,
            'activity': [
                {'date': str(a.date), 'count': a.count}
                for a in activity
            ]
        })

    except Exception as e:
        logger.error(f'Error fetching activity stats: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    # Initialize database
    init_db()
    logger.info('Database initialized')

    # Run API server
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    logger.info(f'Starting Discord Logger API on port {port}')
    app.run(host='0.0.0.0', port=port, debug=debug)
