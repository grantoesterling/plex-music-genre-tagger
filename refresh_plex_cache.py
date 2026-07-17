#!/usr/bin/env python3
"""
Refresh Plex Cache

Simple script to refresh the Plex metadata cache without running the full RYM updater.
Fetches current album metadata from Plex and saves it to the cache file.

Usage:
    python refresh_plex_cache.py
"""

import ssl
import urllib3
import json
import os
from datetime import datetime
from plexapi.server import PlexServer

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

# File paths
CACHE_FILE = "plex_metadata_cache.json"

def connect_to_plex():
    """Connect to Plex server and get music library with optimized timeouts."""
    try:
        print(f"🔌 Connecting to Plex server at {PLEX_URL}...")
        
        # Create session with SSL verification disabled and longer timeouts
        import requests
        session = requests.Session()
        session.verify = False
        
        # Set longer timeouts to prevent connection issues
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

def get_live_plex_albums(music_library):
    """Get album metadata directly from Plex."""
    try:
        print("📡 Fetching albums directly from Plex...")
        albums = music_library.albums()
        
        album_data = []
        albums_processed = 0
        
        for album in albums:
            albums_processed += 1
            
            # Show progress every 50 albums
            if albums_processed % 50 == 0:
                print(f"   Progress: {albums_processed}/{len(albums)} albums processed...")
       
            album_info = {
                'key': album.key,
                'title': album.title,
                'artist': album.parentTitle,
                'year': getattr(album, 'year', None),
                'genres': [g.tag for g in album.genres] if album.genres else [],
                'styles': [s.tag for s in album.styles] if album.styles else [],
                'moods': [m.tag for m in album.moods] if album.moods else []
            }
            album_data.append(album_info)
        
        print(f"✅ Loaded {len(album_data)} albums from Plex")
        return album_data
        
    except Exception as e:
        print(f"❌ Error fetching albums from Plex: {e}")
        return None

def save_metadata_cache(albums_data):
    """Save album metadata to cache file."""
    try:
        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "total_albums": len(albums_data),
            "albums": albums_data
        }
        
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved {len(albums_data)} albums to cache: {CACHE_FILE}")
        
        # Show cache file info
        cache_size_mb = os.path.getsize(CACHE_FILE) / (1024 * 1024)
        print(f"   Cache file size: {cache_size_mb:.1f} MB")
        
    except Exception as e:
        print(f"❌ Error saving cache: {e}")

def show_cache_stats():
    """Show current cache statistics if cache exists."""
    if not os.path.exists(CACHE_FILE):
        print("ℹ️  No existing cache found")
        return
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        timestamp = datetime.fromisoformat(cache_data["timestamp"])
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600
        cache_size_mb = os.path.getsize(CACHE_FILE) / (1024 * 1024)
        
        print(f"📊 Current cache info:")
        print(f"   Last updated: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Cache age: {age_hours:.1f} hours")
        print(f"   Cached albums: {cache_data['total_albums']}")
        print(f"   File size: {cache_size_mb:.1f} MB")
        
    except Exception as e:
        print(f"⚠️  Error reading existing cache: {e}")

def main():
    """Main function."""
    import sys
    
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print("🔄 Refresh Plex Cache")
        print("=" * 50)
        print("Refreshes the Plex metadata cache with current album information.")
        print()
        print("Usage:")
        print("  python refresh_plex_cache.py")
        print()
        print("This script will:")
        print("  1. Connect to your Plex server")
        print("  2. Fetch all album metadata from your music library")
        print("  3. Save it to plex_metadata_cache.json")
        print()
        print("The cache is used by:")
        print("  • rym_plex_updater.py (for faster processing)")
        print("  • Other analysis scripts")
        print()
        print("Run this when:")
        print("  • You've added new albums to Plex")
        print("  • You've changed metadata in Plex")
        print("  • The cache is outdated")
        return
    
    print("🔄 Refresh Plex Cache")
    print("=" * 50)
    
    # Show current cache stats
    show_cache_stats()
    print()
    
    # Connect to Plex
    plex, music_library = connect_to_plex()
    if not music_library:
        return
    
    # Fetch album data
    albums_data = get_live_plex_albums(music_library)
    if not albums_data:
        return
    
    # Save to cache
    save_metadata_cache(albums_data)
    
    print(f"\n✅ Cache refresh complete!")
    print(f"💡 You can now run other scripts that use the cache:")
    print(f"   python rym_plex_updater.py")
    print(f"   python review_genres.py")

if __name__ == "__main__":
    main() 