#!/usr/bin/env python3
"""
Add Mood to Albums by Collection or Genre

Finds all albums in a collection OR all albums of a specific genre 
and adds a mood to them if they don't already have it.

Usage:
    python add_summer_mood_to_collection.py [--collection NAME | --genre NAME] [--mood NAME] [--execute]
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
from typing import List, Optional

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


def find_collection(music_library, collection_name: str):
    """Find a collection by name."""
    try:
        print(f"🔍 Looking for collection: '{collection_name}'")
        collections = music_library.collections()
        
        for collection in collections:
            if collection.title.lower() == collection_name.lower():
                print(f"✅ Found collection: '{collection.title}' with {len(collection.items())} items")
                return collection
        
        print(f"❌ Collection '{collection_name}' not found")
        print(f"📋 Available collections:")
        for collection in collections:
            print(f"   • {collection.title}")
        return None
        
    except Exception as e:
        print(f"❌ Error finding collection: {e}")
        return None


def get_albums_from_collection(collection) -> List:
    """Get all albums from a collection."""
    try:
        items = collection.items()
        albums = [item for item in items if hasattr(item, 'type') and item.type == 'album']
        print(f"📀 Found {len(albums)} albums in collection '{collection.title}'")
        return albums
    except Exception as e:
        print(f"❌ Error getting albums from collection: {e}")
        return []


def get_albums_by_genre(music_library, genre_name: str) -> List:
    """Get all albums with a specific genre using server-side search."""
    try:
        print(f"🔍 Searching for albums with genre: '{genre_name}'")
        
        # Use Plex's server-side search to filter by genre
        # This is much faster than client-side filtering
        matching_albums = music_library.search(
            libtype='album',
            genre=genre_name
        )
        
        print(f"📀 Found {len(matching_albums)} albums with genre '{genre_name}'")
        
        if len(matching_albums) == 0:
            # Show some available genres to help user
            print(f"❌ No albums found with genre '{genre_name}'")
            print(f"💡 Let's check available genres...")
            
            # Get a sample of albums to show available genres
            sample_albums = music_library.albums()[:100]  # Get first 100 albums
            all_genres = set()
            
            print(f"📡 Sampling genres from first {len(sample_albums)} albums...")
            for album in sample_albums:
                try:
                    if hasattr(album, 'genres') and album.genres:
                        for genre in album.genres:
                            all_genres.add(genre.tag)
                except:
                    continue
            
            if all_genres:
                sorted_genres = sorted(list(all_genres))
                print(f"📋 Sample of available genres:")
                for i, genre in enumerate(sorted_genres[:20], 1):  # Show first 20
                    print(f"   {i:2d}. {genre}")
                if len(sorted_genres) > 20:
                    print(f"   ... and {len(sorted_genres) - 20} more")
                
                # Suggest close matches
                genre_lower = genre_name.lower()
                close_matches = [g for g in sorted_genres if genre_lower in g.lower() or g.lower() in genre_lower]
                if close_matches:
                    print(f"🎯 Possible matches:")
                    for match in close_matches[:5]:
                        print(f"   • {match}")
        
        return matching_albums
        
    except Exception as e:
        print(f"❌ Error searching for albums by genre: {e}")
        print(f"💡 Falling back to manual search...")
        
        # Fallback to manual search if server-side search fails
        return get_albums_by_genre_manual(music_library, genre_name)


def get_albums_by_genre_manual(music_library, genre_name: str) -> List:
    """Fallback method: Get all albums with a specific genre using manual filtering."""
    try:
        print(f"🔍 Manual search for albums with genre: '{genre_name}'")
        
        # Get all albums from the library
        all_albums = music_library.albums()
        matching_albums = []
        
        print(f"📡 Scanning {len(all_albums)} albums for genre '{genre_name}'...")
        
        for i, album in enumerate(all_albums, 1):
            # Show progress every 100 albums
            if i % 100 == 0:
                print(f"   Progress: {i}/{len(all_albums)} albums scanned...")
            
            try:
                # Check if album has the specified genre (case-insensitive)
                if hasattr(album, 'genres') and album.genres:
                    album_genres = [g.tag for g in album.genres]
                    if any(genre.lower() == genre_name.lower() for genre in album_genres):
                        matching_albums.append(album)
            except Exception as e:
                # Skip albums that cause errors
                continue
        
        print(f"📀 Found {len(matching_albums)} albums with genre '{genre_name}' (manual search)")
        return matching_albums
        
    except Exception as e:
        print(f"❌ Error in manual search: {e}")
        return []


def check_and_add_mood(album, mood_name: str, dry_run: bool = True) -> bool:
    """Check if album has the mood and add it if not."""
    try:
        # Get existing moods
        existing_moods = [m.tag for m in album.moods] if hasattr(album, 'moods') and album.moods else []
        
        # Check if mood already exists (case-insensitive)
        mood_exists = any(existing_mood.lower() == mood_name.lower() for existing_mood in existing_moods)
        
        if mood_exists:
            return False  # No change needed
        
        if dry_run:
            print(f"   🔍 DRY RUN - Would add '{mood_name}' mood")
            return True
        
        # Add the mood
        album.addMood([mood_name], locked=True)
        print(f"   ✅ Added '{mood_name}' mood")
        return True
        
    except Exception as e:
        print(f"   ❌ Error updating mood for {album.title}: {e}")
        return False


def process_albums_by_filter(music_library, collection_name: str = None, 
                           genre_name: str = None, mood_name: str = "Summer", 
                           dry_run: bool = True) -> None:
    """Process albums by collection or genre and add mood."""
    
    albums = []
    source_description = ""
    
    if collection_name and genre_name:
        print("❌ Error: Cannot specify both --collection and --genre. Choose one.")
        return
    elif collection_name:
        # Process by collection
        collection = find_collection(music_library, collection_name)
        if not collection:
            return
        albums = get_albums_from_collection(collection)
        source_description = f"collection '{collection_name}'"
    elif genre_name:
        # Process by genre
        albums = get_albums_by_genre(music_library, genre_name)
        source_description = f"genre '{genre_name}'"
    else:
        print("❌ Error: Must specify either --collection or --genre")
        return
    
    if not albums:
        print(f"❌ No albums found for {source_description}")
        return
    
    print(f"\n🔄 Processing {len(albums)} albums from {source_description}...")
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
    
    albums_updated = 0
    albums_skipped = 0
    albums_error = 0
    
    for i, album in enumerate(albums, 1):
        try:
            # Force reload to get fresh metadata
            album.reload()
            
            artist = album.parentTitle if hasattr(album, 'parentTitle') else 'Unknown Artist'
            title = album.title
            
            print(f"[{i:3d}/{len(albums)}] {artist} - {title}")
            
            # Check existing moods
            existing_moods = [m.tag for m in album.moods] if hasattr(album, 'moods') and album.moods else []
            mood_exists = any(existing_mood.lower() == mood_name.lower() for existing_mood in existing_moods)
            
            if mood_exists:
                print(f"   ⏭️  Already has '{mood_name}' mood")
                albums_skipped += 1
            else:
                print(f"   📝 Current moods: {existing_moods if existing_moods else 'None'}")
                success = check_and_add_mood(album, mood_name, dry_run)
                if success:
                    albums_updated += 1
                else:
                    albums_error += 1
            
            # Small delay between albums to be nice to Plex
            if not dry_run:
                time.sleep(0.1)
                
        except Exception as e:
            print(f"   ❌ Error processing album: {e}")
            albums_error += 1
    
    # Summary
    print(f"\n📈 Processing Summary:")
    print(f"   Total albums found: {len(albums)}")
    print(f"   Albums already with '{mood_name}' mood: {albums_skipped}")
    if dry_run:
        print(f"   Albums that would be updated: {albums_updated}")
    else:
        print(f"   Albums updated: {albums_updated}")
    print(f"   Errors: {albums_error}")
    
    if dry_run and albums_updated > 0:
        print(f"\n💡 Run with --execute to actually add the '{mood_name}' mood to albums")


def print_help():
    """Print help information."""
    print("🎵 Add Mood to Albums by Collection or Genre")
    print("=" * 50)
    print("Finds all albums in a Plex collection OR all albums with a specific genre")
    print("and adds a mood to them if they don't already have it.")
    print()
    print("Usage:")
    print("  python add_summer_mood_to_collection.py [--collection NAME | --genre NAME] [--mood NAME] [--execute]")
    print()
    print("Options:")
    print("  --collection NAME  Collection name to process")
    print("  --genre NAME       Genre name to filter albums by")
    print("  --mood NAME        Mood to add to albums (default: 'Summer')")
    print("  --execute          Actually update albums (default is dry run)")
    print("  --help, -h         Show this help message")
    print()
    print("Examples:")
    print("  # Add Summer mood to all albums in Summer collection")
    print("  python add_summer_mood_to_collection.py --collection 'Summer' --execute")
    print()
    print("  # Add Summer mood to all Reggae albums")
    print("  python add_summer_mood_to_collection.py --genre 'Reggae' --mood 'Summer' --execute")
    print()
    print("  # Add Summer mood to all MPB albums")
    print("  python add_summer_mood_to_collection.py --genre 'MPB' --mood 'Summer' --execute")
    print()
    print("  # Dry run to see what Bossa Nova albums would be updated")
    print("  python add_summer_mood_to_collection.py --genre 'Bossa Nova'")
    print()
    print("  # Add different mood to different collection")
    print("  python add_summer_mood_to_collection.py --collection 'Chill Vibes' --mood 'Relaxing' --execute")
    print()
    print("Notes:")
    print("  • Must specify either --collection OR --genre (not both)")
    print("  • Script checks if mood already exists before adding")
    print("  • Collection and genre names are case-insensitive for matching")
    print("  • Mood names are case-sensitive when added")
    print("  • Only works with album collections")
    print("  • Genre matching checks if album has the specified genre")


def main():
    """Main function."""
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        return
    
    print("🎵 Add Mood to Albums by Collection or Genre")
    print("=" * 50)
    
    # Parse command line arguments
    collection_name = None
    genre_name = None
    mood_name = "Summer"
    execute = False
    
    for i, arg in enumerate(sys.argv):
        if arg == "--collection" and i + 1 < len(sys.argv):
            collection_name = sys.argv[i + 1]
        elif arg == "--genre" and i + 1 < len(sys.argv):
            genre_name = sys.argv[i + 1]
        elif arg == "--mood" and i + 1 < len(sys.argv):
            mood_name = sys.argv[i + 1]
        elif arg == "--execute":
            execute = True
    
    # Validate arguments
    if not collection_name and not genre_name:
        print("❌ Error: Must specify either --collection or --genre")
        print("Use --help for usage information")
        return
    
    if collection_name and genre_name:
        print("❌ Error: Cannot specify both --collection and --genre. Choose one.")
        print("Use --help for usage information")
        return
    
    # Show what we're doing
    if collection_name:
        print(f"🎯 Target collection: '{collection_name}'")
    else:
        print(f"🎵 Target genre: '{genre_name}'")
    
    print(f"🏷️  Mood to add: '{mood_name}'")
    print(f"🔄 Mode: {'EXECUTE' if execute else 'DRY RUN'}")
    
    # Connect to Plex
    print("\n🔌 Connecting to Plex...")
    plex, music_library = connect_to_plex()
    if not music_library:
        return
    
    # Process the albums
    process_albums_by_filter(
        music_library=music_library,
        collection_name=collection_name,
        genre_name=genre_name,
        mood_name=mood_name,
        dry_run=not execute
    )
    
    if not execute:
        print(f"\n💡 This was a dry run. Use --execute to actually add moods.")


if __name__ == "__main__":
    main() 