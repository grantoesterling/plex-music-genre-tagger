import os
import json
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound, BadRequest
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
PLEX_URL = os.environ.get('PLEX_URL', 'http://localhost:32400')
PLEX_TOKEN = os.environ.get('PLEX_TOKEN', '')
MUSIC_LIBRARY_NAME = os.environ.get('MUSIC_LIBRARY_NAME', 'Music')
CACHE_DURATION_HOURS = int(os.environ.get('CACHE_DURATION_HOURS', '24'))

# Global variables for caching
music_releases_cache = None
cache_timestamp = None

def get_plex_server():
    """Initialize and return Plex server connection"""
    try:
        return PlexServer(PLEX_URL, PLEX_TOKEN)
    except Exception as e:
        logger.error(f"Failed to connect to Plex server: {e}")
        raise

def is_cache_valid():
    """Check if the cache is still valid based on timestamp"""
    if cache_timestamp is None:
        return False
    
    cache_age = datetime.now() - cache_timestamp
    return cache_age < timedelta(hours=CACHE_DURATION_HOURS)

def fetch_music_releases():
    """Fetch all music releases from Plex library"""
    global music_releases_cache, cache_timestamp
    
    try:
        plex = get_plex_server()
        music_library = plex.library.section(MUSIC_LIBRARY_NAME)
        
        logger.info("Fetching all albums from Plex library...")
        albums = music_library.albums()
        
        releases = []
        for album in albums:
            try:
                # Get album metadata
                release_data = {
                    'id': album.ratingKey,
                    'title': album.title,
                    'artist': album.parentTitle if hasattr(album, 'parentTitle') else 'Unknown Artist',
                    'year': album.year,
                    'genres': [genre.tag for genre in album.genres] if hasattr(album, 'genres') else [],
                    'moods': [mood.tag for mood in album.moods] if hasattr(album, 'moods') else [],
                    'summary': album.summary if hasattr(album, 'summary') else '',
                    'thumb': album.thumb if hasattr(album, 'thumb') else None,
                    'addedAt': album.addedAt.isoformat() if hasattr(album, 'addedAt') and album.addedAt else None,
                    'updatedAt': album.updatedAt.isoformat() if hasattr(album, 'updatedAt') and album.updatedAt else None
                }
                releases.append(release_data)
            except Exception as e:
                logger.warning(f"Error processing album {album.title}: {e}")
                continue
        
        # Update cache
        music_releases_cache = releases
        cache_timestamp = datetime.now()
        
        logger.info(f"Successfully cached {len(releases)} music releases")
        return releases
        
    except Exception as e:
        logger.error(f"Error fetching music releases: {e}")
        raise

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        plex = get_plex_server()
        return jsonify({
            'status': 'healthy',
            'plex_connected': True,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'plex_connected': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/releases', methods=['GET'])
def get_releases():
    """Get all music releases with optional caching"""
    global music_releases_cache
    
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    try:
        # Check if we need to refresh cache
        if force_refresh or not is_cache_valid() or music_releases_cache is None:
            logger.info("Refreshing music releases cache...")
            releases = fetch_music_releases()
        else:
            logger.info("Using cached music releases")
            releases = music_releases_cache
        
        return jsonify({
            'releases': releases,
            'total_count': len(releases),
            'cached': not force_refresh and is_cache_valid(),
            'cache_timestamp': cache_timestamp.isoformat() if cache_timestamp else None,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error in get_releases: {e}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/releases/<int:release_id>/moods', methods=['POST'])
def add_moods_to_release(release_id):
    """Add moods to a specific release"""
    try:
        data = request.get_json()
        if not data or 'moods' not in data:
            return jsonify({'error': 'Missing moods in request body'}), 400
        
        moods = data['moods']
        if not isinstance(moods, list):
            return jsonify({'error': 'Moods must be a list'}), 400
        
        # Connect to Plex and get the album
        plex = get_plex_server()
        album = plex.fetchItem(release_id)
        
        if album.type != 'album':
            return jsonify({'error': 'Item is not an album'}), 400
        
        # Get existing moods
        existing_moods = [mood.tag for mood in album.moods] if hasattr(album, 'moods') else []
        
        # Add new moods (avoiding duplicates)
        new_moods = list(set(existing_moods + moods))
        
        # Update album with new moods
        album.editMoods(new_moods)
        
        # Invalidate cache since we modified data
        global music_releases_cache, cache_timestamp
        music_releases_cache = None
        cache_timestamp = None
        
        logger.info(f"Added moods {moods} to album: {album.title}")
        
        return jsonify({
            'success': True,
            'album_id': release_id,
            'album_title': album.title,
            'previous_moods': existing_moods,
            'new_moods': new_moods,
            'added_moods': moods,
            'timestamp': datetime.now().isoformat()
        })
        
    except NotFound:
        return jsonify({'error': f'Release with ID {release_id} not found'}), 404
    except BadRequest as e:
        return jsonify({'error': f'Bad request: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error adding moods to release {release_id}: {e}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/releases/<int:release_id>/moods', methods=['GET'])
def get_release_moods(release_id):
    """Get moods for a specific release"""
    try:
        plex = get_plex_server()
        album = plex.fetchItem(release_id)
        
        if album.type != 'album':
            return jsonify({'error': 'Item is not an album'}), 400
        
        moods = [mood.tag for mood in album.moods] if hasattr(album, 'moods') else []
        
        return jsonify({
            'album_id': release_id,
            'album_title': album.title,
            'artist': album.parentTitle if hasattr(album, 'parentTitle') else 'Unknown Artist',
            'moods': moods,
            'timestamp': datetime.now().isoformat()
        })
        
    except NotFound:
        return jsonify({'error': f'Release with ID {release_id} not found'}), 404
    except Exception as e:
        logger.error(f"Error getting moods for release {release_id}: {e}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    """Clear the music releases cache"""
    global music_releases_cache, cache_timestamp
    
    music_releases_cache = None
    cache_timestamp = None
    
    return jsonify({
        'success': True,
        'message': 'Cache cleared successfully',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/cache/status', methods=['GET'])
def cache_status():
    """Get cache status information"""
    return jsonify({
        'cache_exists': music_releases_cache is not None,
        'cache_valid': is_cache_valid(),
        'cache_timestamp': cache_timestamp.isoformat() if cache_timestamp else None,
        'cache_size': len(music_releases_cache) if music_releases_cache else 0,
        'cache_duration_hours': CACHE_DURATION_HOURS,
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    # Validate required environment variables
    if not PLEX_TOKEN:
        logger.error("PLEX_TOKEN environment variable is required")
        exit(1)
    
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true') 