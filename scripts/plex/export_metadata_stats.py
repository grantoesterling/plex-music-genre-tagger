#!/usr/bin/env python3
"""
Export Plex Metadata Statistics Script

Connects to Plex server, scrapes all music releases, and exports JSON statistics
showing all genres and moods used in the database along with their usage counts.
"""

import ssl
import urllib3
import json
import os
import logging
import time
import sys
from datetime import datetime
from plexapi.server import PlexServer
from collections import defaultdict
from typing import Dict, List, Set

# Disable SSL warnings and verification
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

# Import configuration
try:
    from config import PLEX_URL, PLEX_TOKEN, MUSIC_LIBRARY_NAME
except ImportError:
    print("❌ Error: config.py not found!")
    print("Please copy config.py.example to config.py and fill in your details.")
    exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress verbose logging from external libraries
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)


def connect_to_plex():
    """Connect to Plex server and get music library."""
    try:
        print(f"🔌 Connecting to Plex server at {PLEX_URL}...")
        
        # Create session with SSL verification disabled
        import requests
        session = requests.Session()
        session.verify = False
        session.timeout = (10, 60)  # 10s to connect, 60s to read
        
        # Configure session for better performance
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        plex = PlexServer(PLEX_URL, PLEX_TOKEN, session=session, timeout=60)
        
        print(f"📚 Accessing music library: {MUSIC_LIBRARY_NAME}")
        music_library = plex.library.section(MUSIC_LIBRARY_NAME)
        
        return plex, music_library
    except Exception as e:
        print(f"❌ Error connecting to Plex: {e}")
        return None, None


def get_all_albums(music_library):
    """Get all albums from Plex music library with fresh data."""
    try:
        print("📡 Fetching all albums from Plex (forcing fresh data)...")
        # Force fresh data by reloading the library section
        music_library.reload()
        albums = music_library.albums()
        print(f"✅ Found {len(albums)} albums in library")
        return albums
    except Exception as e:
        print(f"❌ Error fetching albums: {e}")
        return []


def collect_metadata_stats(albums: List) -> Dict:
    """
    Collect statistics for all genres, styles, and moods used in the albums.
    Keeps genres and styles separate as they are different fields in Plex.
    
    Returns:
        Dict with genre, style, and mood statistics
    """
    genre_counts = defaultdict(int)
    style_counts = defaultdict(int)
    mood_counts = defaultdict(int)
    
    total_albums = len(albums)
    processed = 0
    
    print(f"\n📊 Analyzing metadata from {total_albums} albums...")
    
    for i, album in enumerate(albums, 1):
        try:
            album_title = f"{getattr(album, 'parentTitle', 'Unknown')} - {getattr(album, 'title', 'Unknown')}"
            
            # Progress indicator
            if i % 100 == 0 or i == total_albums:
                print(f"   Progress: {i}/{total_albums} albums processed...")
            
            # Force reload of album data to ensure fresh metadata
            album.reload()
            
            # Collect genres (separate from styles)
            if hasattr(album, 'genres') and album.genres:
                for genre in album.genres:
                    if hasattr(genre, 'tag'):
                        genre_counts[genre.tag] += 1
            
            # Collect styles (separate from genres)
            if hasattr(album, 'styles') and album.styles:
                for style in album.styles:
                    if hasattr(style, 'tag'):
                        style_counts[style.tag] += 1
            
            # Collect moods
            if hasattr(album, 'moods') and album.moods:
                for mood in album.moods:
                    if hasattr(mood, 'tag'):
                        mood_counts[mood.tag] += 1
            
            processed += 1
            
        except Exception as e:
            print(f"   ⚠️ Error processing album {i}: {e}")
            continue
    
    print(f"✅ Successfully processed {processed} albums")
    
    # Convert defaultdicts to regular dicts and sort by count (descending)
    genre_stats = dict(sorted(genre_counts.items(), key=lambda x: x[1], reverse=True))
    style_stats = dict(sorted(style_counts.items(), key=lambda x: x[1], reverse=True))
    mood_stats = dict(sorted(mood_counts.items(), key=lambda x: x[1], reverse=True))
    
    return {
        'genres': genre_stats,
        'styles': style_stats,
        'moods': mood_stats,
        'summary': {
            'total_albums_processed': processed,
            'unique_genres': len(genre_stats),
            'unique_styles': len(style_stats),
            'unique_moods': len(mood_stats),
            'total_genre_assignments': sum(genre_stats.values()),
            'total_style_assignments': sum(style_stats.values()),
            'total_mood_assignments': sum(mood_stats.values())
        }
    }


def export_stats_to_json(stats: Dict, filename: str = None) -> str:
    """Export metadata statistics to JSON file."""
    if filename is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"plex_metadata_stats_{timestamp}.json"
    
    try:
        # Add metadata about the export
        export_data = {
            'export_info': {
                'timestamp': datetime.now().isoformat(),
                'script_version': '1.0',
                'description': 'Plex music library metadata usage statistics'
            },
            'statistics': stats
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Exported metadata statistics to: {filename}")
        return filename
        
    except Exception as e:
        print(f"❌ Error exporting statistics: {e}")
        return None


def print_summary(stats: Dict):
    """Print a summary of the collected statistics."""
    summary = stats['summary']
    
    print(f"\n📈 Metadata Statistics Summary:")
    print(f"   Total albums processed: {summary['total_albums_processed']}")
    print(f"   Unique genres found: {summary['unique_genres']}")
    print(f"   Unique styles found: {summary['unique_styles']}")
    print(f"   Unique moods found: {summary['unique_moods']}")
    print(f"   Total genre assignments: {summary['total_genre_assignments']}")
    print(f"   Total style assignments: {summary['total_style_assignments']}")
    print(f"   Total mood assignments: {summary['total_mood_assignments']}")
    
    # Show top 10 most used items in each category
    print(f"\n🏆 Top 10 Most Used Genres:")
    for i, (genre, count) in enumerate(list(stats['genres'].items())[:10], 1):
        print(f"   {i:2d}. {genre}: {count} albums")
    
    if stats['styles']:
        print(f"\n🎨 Top 10 Most Used Styles:")
        for i, (style, count) in enumerate(list(stats['styles'].items())[:10], 1):
            print(f"   {i:2d}. {style}: {count} albums")
    
    if stats['moods']:
        print(f"\n😊 Top 10 Most Used Moods:")
        for i, (mood, count) in enumerate(list(stats['moods'].items())[:10], 1):
            print(f"   {i:2d}. {mood}: {count} albums")


def main():
    """Main function."""
    
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print("📊 Export Plex Metadata Statistics Script")
        print("=" * 50)
        print("Connects to Plex server, scrapes all music releases, and exports")
        print("JSON statistics showing genre and mood usage counts.")
        print()
        print("Usage:")
        print("  python export_plex_metadata_stats.py [options]")
        print()
        print("Options:")
        print("  --output FILE      Specify output filename (default: auto-generated)")
        print("  --limit N          Only process first N albums (for testing)")
        print("  --help, -h         Show this help message")
        return
    
    print("📊 Export Plex Metadata Statistics Script")
    print("=" * 50)
    
    # Parse command line arguments
    output_file = None
    limit = None
    
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            output_file = sys.argv[i + 1]
        elif arg == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
                if limit < 1:
                    print("❌ Limit must be at least 1")
                    return
            except ValueError:
                print("❌ Invalid limit. Must be a number.")
                return
    
    # Connect to Plex
    print("🔌 Connecting to Plex...")
    plex, music_library = connect_to_plex()
    if not music_library:
        return
    
    # Get all albums
    albums = get_all_albums(music_library)
    if not albums:
        return
    
    # Apply limit if specified
    if limit:
        original_count = len(albums)
        albums = albums[:limit]
        print(f"🧪 Testing mode: Processing first {len(albums)} of {original_count} albums (--limit {limit})")
    
    # Collect metadata statistics
    stats = collect_metadata_stats(albums)
    
    # Print summary
    print_summary(stats)
    
    # Export to JSON
    exported_file = export_stats_to_json(stats, output_file)
    
    if exported_file:
        print(f"\n✅ Export completed successfully!")
        print(f"   File saved as: {exported_file}")
        print(f"   File size: {os.path.getsize(exported_file):,} bytes")
    else:
        print(f"\n❌ Export failed!")


if __name__ == "__main__":
    main()






