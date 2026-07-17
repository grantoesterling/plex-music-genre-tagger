#!/usr/bin/env python3
"""
Find Albums with No Moods

Queries the Plex library to find all releases (albums) that have 0 moods assigned.
Exports the results to JSON and displays summary statistics.

Usage:
    python find_albums_with_no_moods.py [--output FILE] [--limit N] [--verbose]
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
from typing import Dict, List, Optional

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


def get_all_albums(music_library, limit: Optional[int] = None):
    """Get all albums from Plex music library."""
    try:
        print("📡 Fetching all albums from Plex...")
        albums = music_library.albums()
        print(f"✅ Found {len(albums)} albums in library")
        
        if limit:
            albums = albums[:limit]
            print(f"🧪 Limited to first {len(albums)} albums for testing")
        
        return albums
    except Exception as e:
        print(f"❌ Error fetching albums: {e}")
        return []


def find_albums_with_no_moods(albums: List, verbose: bool = False) -> List[Dict]:
    """
    Find all albums that have no moods assigned.
    
    Returns:
        List of album dictionaries with key info for albums with 0 moods
    """
    albums_no_moods = []
    total_albums = len(albums)
    processed = 0
    
    print(f"\n🔍 Analyzing {total_albums} albums for mood metadata...")
    
    for i, album in enumerate(albums, 1):
        try:
            # Force reload to get fresh metadata
            album.reload()
            
            # Progress indicator
            if i % 50 == 0 or i == total_albums:
                print(f"   Progress: {i}/{total_albums} albums processed...")
            
            # Check if album has no moods
            has_moods = hasattr(album, 'moods') and album.moods and len(album.moods) > 0
            
            if not has_moods:
                # Collect album information
                album_info = {
                    'key': album.key,
                    'title': album.title,
                    'artist': album.parentTitle if hasattr(album, 'parentTitle') else 'Unknown Artist',
                    'year': getattr(album, 'year', None),
                    'added_at': album.addedAt.isoformat() if hasattr(album, 'addedAt') and album.addedAt else None,
                    'updated_at': album.updatedAt.isoformat() if hasattr(album, 'updatedAt') and album.updatedAt else None,
                    'genres': [g.tag for g in album.genres] if hasattr(album, 'genres') and album.genres else [],
                    'styles': [s.tag for s in album.styles] if hasattr(album, 'styles') and album.styles else [],
                    'moods': [],  # Explicitly showing this is empty
                    'track_count': getattr(album, 'leafCount', 0)
                }
                
                albums_no_moods.append(album_info)
                
                if verbose:
                    print(f"   🎵 No moods: {album_info['artist']} - {album_info['title']} ({album_info['year'] or 'Unknown'})")
            
            processed += 1
            
        except Exception as e:
            print(f"   ⚠️ Error processing album {i}: {e}")
            continue
    
    print(f"✅ Successfully processed {processed} albums")
    print(f"📊 Found {len(albums_no_moods)} albums with no moods ({len(albums_no_moods)/processed*100:.1f}%)")
    
    return albums_no_moods


def export_results_to_json(albums_no_moods: List[Dict], filename: str = None) -> str:
    """Export albums with no moods to JSON file."""
    if filename is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"albums_no_moods_{timestamp}.json"
    
    try:
        # Prepare export data
        export_data = {
            'export_info': {
                'timestamp': datetime.now().isoformat(),
                'script_version': '1.0',
                'description': 'Albums from Plex music library with no moods assigned',
                'total_albums_found': len(albums_no_moods)
            },
            'albums': albums_no_moods
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Exported results to: {filename}")
        return filename
        
    except Exception as e:
        print(f"❌ Error exporting results: {e}")
        return None


def print_summary(albums_no_moods: List[Dict]):
    """Print a detailed summary of albums with no moods."""
    if not albums_no_moods:
        print("\n🎉 All albums have moods assigned!")
        return
    
    print(f"\n📈 Summary of Albums with No Moods:")
    print(f"   Total albums without moods: {len(albums_no_moods)}")
    
    # Group by artist
    by_artist = {}
    for album in albums_no_moods:
        artist = album['artist']
        if artist not in by_artist:
            by_artist[artist] = []
        by_artist[artist].append(album)
    
    print(f"   Number of unique artists: {len(by_artist)}")
    
    # Show top artists with most albums missing moods
    sorted_artists = sorted(by_artist.items(), key=lambda x: len(x[1]), reverse=True)
    print(f"\n🎭 Top artists with albums missing moods:")
    for i, (artist, artist_albums) in enumerate(sorted_artists[:10], 1):
        print(f"   {i:2d}. {artist}: {len(artist_albums)} album(s)")
    
    # Show year distribution
    years = [album['year'] for album in albums_no_moods if album['year']]
    if years:
        year_counts = {}
        for year in years:
            decade = (year // 10) * 10
            year_counts[decade] = year_counts.get(decade, 0) + 1
        
        print(f"\n📅 Distribution by decade:")
        for decade in sorted(year_counts.keys()):
            print(f"   {decade}s: {year_counts[decade]} album(s)")
    
    # Show albums with genres but no moods
    albums_with_genres = [album for album in albums_no_moods if album['genres']]
    albums_with_styles = [album for album in albums_no_moods if album['styles']]
    albums_with_any_metadata = [album for album in albums_no_moods if album['genres'] or album['styles']]
    albums_with_no_metadata = len(albums_no_moods) - len(albums_with_any_metadata)
    
    print(f"\n🏷️  Metadata status:")
    print(f"   Albums with genres but no moods: {len(albums_with_genres)}")
    print(f"   Albums with styles but no moods: {len(albums_with_styles)}")
    print(f"   Albums with no metadata at all: {albums_with_no_metadata}")


def print_help():
    """Print help information."""
    print("🎵 Find Albums with No Moods")
    print("=" * 50)
    print("Queries the Plex library to find all releases with 0 moods assigned.")
    print()
    print("Usage:")
    print("  python find_albums_with_no_moods.py [options]")
    print()
    print("Options:")
    print("  --output FILE      Specify output filename (default: auto-generated)")
    print("  --limit N          Only process first N albums (for testing)")
    print("  --verbose          Show each album found without moods")
    print("  --help, -h         Show this help message")
    print()
    print("Examples:")
    print("  # Find all albums with no moods")
    print("  python find_albums_with_no_moods.py")
    print()
    print("  # Test with first 100 albums only")
    print("  python find_albums_with_no_moods.py --limit 100")
    print()
    print("  # Export to specific filename with verbose output")
    print("  python find_albums_with_no_moods.py --output my_results.json --verbose")
    print()
    print("Output:")
    print("  • JSON file with detailed album information")
    print("  • Summary statistics printed to console")
    print("  • Albums are sorted by artist name")


def main():
    """Main function."""
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        return
    
    print("🎵 Find Albums with No Moods")
    print("=" * 50)
    
    # Parse command line arguments
    output_file = None
    limit = None
    verbose = False
    
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
        elif arg == "--verbose":
            verbose = True
    
    # Connect to Plex
    print("🔌 Connecting to Plex...")
    plex, music_library = connect_to_plex()
    if not music_library:
        return
    
    # Get all albums
    albums = get_all_albums(music_library, limit)
    if not albums:
        return
    
    # Find albums with no moods
    albums_no_moods = find_albums_with_no_moods(albums, verbose)
    
    # Sort results by artist, then by album title
    albums_no_moods.sort(key=lambda x: (x['artist'].lower(), x['title'].lower()))
    
    # Print summary
    print_summary(albums_no_moods)
    
    # Export results
    if albums_no_moods:
        export_filename = export_results_to_json(albums_no_moods, output_file)
        if export_filename:
            print(f"\n💡 Next steps:")
            print(f"   • Review the exported file: {export_filename}")
            print(f"   • Use rym_plex_updater.py to add mood metadata")
            print(f"   • Use clean_plex_metadata.py to clean invalid moods")
    else:
        print(f"\n🎉 Great! All albums in your library have moods assigned.")


if __name__ == "__main__":
    main() 