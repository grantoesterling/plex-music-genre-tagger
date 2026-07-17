#!/usr/bin/env python3
"""
Clean Plex Metadata Script

Removes invalid metadata from Plex music library:
- Removes genres/styles not found in rym-genre-tree.json
- Removes moods not found in rym-descriptor-tree.json
- Case-insensitive matching
"""

import ssl
import urllib3
import json
import os
import csv
import logging
import time
import sys
from datetime import datetime
from plexapi.server import PlexServer
from rym_genre_hierarchy import RYMGenreHierarchy
from typing import Dict, List, Set, Tuple

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

# File paths
RYM_DESCRIPTOR_TREE_FILE = "./data/rym-descriptor-tree.json"


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


def load_rym_descriptor_tree() -> Set[str]:
    """Load RYM descriptor tree and extract all valid descriptor names."""
    if not os.path.exists(RYM_DESCRIPTOR_TREE_FILE):
        print(f"⚠️  RYM descriptor tree file not found: {RYM_DESCRIPTOR_TREE_FILE}")
        return set()
    
    try:
        with open(RYM_DESCRIPTOR_TREE_FILE, 'r', encoding='utf-8') as f:
            tree_data = json.load(f)
        
        descriptors = set()
        
        def extract_descriptors(node):
            """Recursively extract descriptor names from the tree."""
            if isinstance(node, dict):
                if 'name' in node:
                    descriptors.add(node['name'].lower().strip())
                if 'children' in node:
                    for child in node['children']:
                        extract_descriptors(child)
            elif isinstance(node, list):
                for item in node:
                    extract_descriptors(item)
        
        # Extract from the descriptor hierarchy
        if 'descriptorHierarchy' in tree_data:
            extract_descriptors(tree_data['descriptorHierarchy'])
        else:
            # If the structure is different, extract from the entire tree
            extract_descriptors(tree_data)
        
        print(f"📊 Loaded {len(descriptors)} valid descriptors from RYM tree")
        return descriptors
        
    except Exception as e:
        print(f"⚠️  Error loading RYM descriptor tree: {e}")
        return set()


def get_all_albums(music_library):
    """Get all albums from Plex music library."""
    try:
        print("📡 Fetching all albums from Plex...")
        albums = music_library.albums()
        print(f"✅ Found {len(albums)} albums in library")
        return albums
    except Exception as e:
        print(f"❌ Error fetching albums: {e}")
        return []


def normalize_tag(tag: str) -> str:
    """Normalize a tag for case-insensitive comparison."""
    return tag.lower().strip()


def filter_invalid_metadata(
    genres: List[str], 
    styles: List[str], 
    moods: List[str], 
    valid_genres: Set[str], 
    valid_descriptors: Set[str]
) -> Tuple[List[str], List[str], List[str], Dict[str, List[str]]]:
    """
    Filter out invalid genres, styles, and moods.
    
    Returns:
        Tuple of (valid_genres, valid_styles, valid_moods, removed_tags)
    """
    
    def filter_tags(tags: List[str], valid_set: Set[str], tag_type: str) -> Tuple[List[str], List[str]]:
        """Filter tags against valid set, return (valid, invalid)."""
        valid = []
        invalid = []
        
        for tag in tags:
            normalized_tag = normalize_tag(tag)
            if normalized_tag in valid_set:
                valid.append(tag)  # Keep original case
            else:
                invalid.append(tag)
        
        return valid, invalid
    
    # Filter genres and styles against RYM genre tree
    valid_genres_list, invalid_genres = filter_tags(genres, valid_genres, "genres")
    valid_styles_list, invalid_styles = filter_tags(styles, valid_genres, "styles")
    
    # Filter moods against RYM descriptor tree
    valid_moods_list, invalid_moods = filter_tags(moods, valid_descriptors, "moods")
    
    removed_tags = {
        'genres': invalid_genres,
        'styles': invalid_styles,
        'moods': invalid_moods
    }
    
    return valid_genres_list, valid_styles_list, valid_moods_list, removed_tags


def clean_album_metadata(album, valid_genres: Set[str], valid_descriptors: Set[str], dry_run: bool = True) -> Dict:
    """
    Clean metadata for a single album.
    
    Returns:
        Dict with cleaning results
    """
    try:
        # Get current metadata
        current_genres = [g.tag for g in album.genres] if album.genres else []
        current_styles = [s.tag for s in album.styles] if album.styles else []
        current_moods = [m.tag for m in album.moods] if album.moods else []
        
        # Filter invalid metadata
        valid_genres_list, valid_styles_list, valid_moods_list, removed_tags = filter_invalid_metadata(
            current_genres, current_styles, current_moods, valid_genres, valid_descriptors
        )
        
        # Check if any changes are needed
        total_removed = len(removed_tags['genres']) + len(removed_tags['styles']) + len(removed_tags['moods'])
        
        if total_removed == 0:
            return {
                'status': 'no_changes',
                'album': f"{album.parentTitle} - {album.title}",
                'removed_tags': removed_tags
            }
        
        if dry_run:
            return {
                'status': 'would_clean',
                'album': f"{album.parentTitle} - {album.title}",
                'removed_tags': removed_tags,
                'before': {
                    'genres': len(current_genres),
                    'styles': len(current_styles),
                    'moods': len(current_moods)
                },
                'after': {
                    'genres': len(valid_genres_list),
                    'styles': len(valid_styles_list),
                    'moods': len(valid_moods_list)
                }
            }
        
        # Actually clean the metadata - remove only invalid tags individually
        success = True
        
        # Remove invalid genres one by one
        if removed_tags['genres']:
            print(f"      🎵 Removing {len(removed_tags['genres'])} invalid genres...")
            try:
                for genre in removed_tags['genres']:
                    print(f"         - Genre: '{genre}'")
                    album.removeGenre(genre, locked=True)
                    time.sleep(0.1)  # Small delay between individual removals
            except Exception as e:
                print(f"      ⚠️ Warning: Error removing genres: {e}")
                success = False
        
        # Remove invalid styles one by one
        if removed_tags['styles']:
            print(f"      🎨 Removing {len(removed_tags['styles'])} invalid styles...")
            try:
                for style in removed_tags['styles']:
                    print(f"         - Style: '{style}'")
                    album.removeStyle(style, locked=True)
                    time.sleep(0.1)  # Small delay between individual removals
            except Exception as e:
                print(f"      ⚠️ Warning: Error removing styles: {e}")
                success = False
        
        # Remove invalid moods one by one
        if removed_tags['moods']:
            print(f"      😊 Removing {len(removed_tags['moods'])} invalid moods...")
            try:
                for mood in removed_tags['moods']:
                    print(f"         - Mood: '{mood}'")
                    album.removeMood(mood, locked=True)
                    time.sleep(0.1)  # Small delay between individual removals
            except Exception as e:
                print(f"      ⚠️ Warning: Error removing moods: {e}")
                success = False
        
        # Add a small delay after all removals to ensure they are processed
        if total_removed > 0:
            time.sleep(0.5)
            print(f"      ✅ Cleanup complete. Remaining valid tags:")
            if valid_genres_list:
                print(f"         Genres ({len(valid_genres_list)}): {', '.join(valid_genres_list)}")
            if valid_styles_list:
                print(f"         Styles ({len(valid_styles_list)}): {', '.join(valid_styles_list)}")
            if valid_moods_list:
                print(f"         Moods ({len(valid_moods_list)}): {', '.join(valid_moods_list)}")
            if not any([valid_genres_list, valid_styles_list, valid_moods_list]):
                print(f"         No valid tags remaining")
        
        return {
            'status': 'cleaned' if success else 'partial_clean',
            'album': f"{album.parentTitle} - {album.title}",
            'removed_tags': removed_tags,
            'before': {
                'genres': len(current_genres),
                'styles': len(current_styles),
                'moods': len(current_moods)
            },
            'after': {
                'genres': len(valid_genres_list),
                'styles': len(valid_styles_list),
                'moods': len(valid_moods_list)
            }
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'album': f"{getattr(album, 'parentTitle', 'Unknown')} - {getattr(album, 'title', 'Unknown')}",
            'error': str(e)
        }


def export_removed_tags(results: List[Dict], filename: str = None):
    """Export details of removed tags to CSV."""
    if filename is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"removed_tags_{timestamp}.csv"
    
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Album', 'Tag_Type', 'Removed_Tag', 
                'Before_Genres', 'After_Genres',
                'Before_Styles', 'After_Styles', 
                'Before_Moods', 'After_Moods'
            ])
            
            for result in results:
                if result['status'] in ['cleaned', 'would_clean'] and result.get('removed_tags'):
                    album = result['album']
                    before = result.get('before', {})
                    after = result.get('after', {})
                    
                    # Write each removed tag as a separate row
                    for tag_type, removed_tags in result['removed_tags'].items():
                        for tag in removed_tags:
                            writer.writerow([
                                album, tag_type, tag,
                                before.get('genres', 0), after.get('genres', 0),
                                before.get('styles', 0), after.get('styles', 0),
                                before.get('moods', 0), after.get('moods', 0)
                            ])
        
        print(f"📝 Exported removed tags details to: {filename}")
        
    except Exception as e:
        print(f"❌ Error exporting removed tags: {e}")


def clean_all_albums(music_library, valid_genres: Set[str], valid_descriptors: Set[str], 
                    dry_run: bool = True, batch_size: int = 50, limit: int = None, verbose: bool = False):
    """Clean metadata for all albums in the library."""
    
    # Get all albums
    albums = get_all_albums(music_library)
    if not albums:
        return
    
    # Apply limit if specified
    if limit:
        original_count = len(albums)
        albums = albums[:limit]
        print(f"🧪 Testing mode: Processing first {len(albums)} of {original_count} albums (--limit {limit})")
    
    total_albums = len(albums)
    results = []
    
    print(f"\n🧹 {'DRY RUN: Analyzing' if dry_run else 'Cleaning'} {total_albums} albums...")
    
    for i, album in enumerate(albums, 1):
        print(f"[{i}/{total_albums}] {getattr(album, 'parentTitle', 'Unknown')} - {getattr(album, 'title', 'Unknown')}")
        
        result = clean_album_metadata(album, valid_genres, valid_descriptors, dry_run)
        results.append(result)
        
        # Show progress for albums that need cleaning
        if result['status'] == 'would_clean':
            removed = result['removed_tags']
            total_removed = len(removed['genres']) + len(removed['styles']) + len(removed['moods'])
            print(f"   🔍 Would remove {total_removed} invalid tags:")
            if removed['genres']:
                print(f"      Genres ({len(removed['genres'])}): {', '.join(removed['genres'])}")
            if removed['styles']:
                print(f"      Styles ({len(removed['styles'])}): {', '.join(removed['styles'])}")
            if removed['moods']:
                print(f"      Moods ({len(removed['moods'])}): {', '.join(removed['moods'])}")
        
        elif result['status'] == 'cleaned':
            removed = result['removed_tags']
            total_removed = len(removed['genres']) + len(removed['styles']) + len(removed['moods'])
            print(f"   ✅ Removed {total_removed} invalid tags:")
            if removed['genres']:
                print(f"      Genres ({len(removed['genres'])}): {', '.join(removed['genres'])}")
            if removed['styles']:
                print(f"      Styles ({len(removed['styles'])}): {', '.join(removed['styles'])}")
            if removed['moods']:
                print(f"      Moods ({len(removed['moods'])}): {', '.join(removed['moods'])}")
        
        elif result['status'] == 'partial_clean':
            removed = result['removed_tags']
            total_removed = len(removed['genres']) + len(removed['styles']) + len(removed['moods'])
            print(f"   ⚠️ Partially cleaned {total_removed} invalid tags (some errors occurred):")
            if removed['genres']:
                print(f"      Genres ({len(removed['genres'])}): {', '.join(removed['genres'])}")
            if removed['styles']:
                print(f"      Styles ({len(removed['styles'])}): {', '.join(removed['styles'])}")
            if removed['moods']:
                print(f"      Moods ({len(removed['moods'])}): {', '.join(removed['moods'])}")
        
        elif result['status'] == 'no_changes':
            print(f"   ✨ Already clean - no invalid tags found")
            if verbose:
                # Show current valid tags for albums that are already clean
                current_genres = [g.tag for g in album.genres] if album.genres else []
                current_styles = [s.tag for s in album.styles] if album.styles else []
                current_moods = [m.tag for m in album.moods] if album.moods else []
                
                if any([current_genres, current_styles, current_moods]):
                    print(f"      Current valid tags:")
                    if current_genres:
                        print(f"         Genres ({len(current_genres)}): {', '.join(current_genres)}")
                    if current_styles:
                        print(f"         Styles ({len(current_styles)}): {', '.join(current_styles)}")
                    if current_moods:
                        print(f"         Moods ({len(current_moods)}): {', '.join(current_moods)}")
                else:
                    print(f"      No tags currently assigned")
        
        elif result['status'] == 'error':
            print(f"   ❌ Error: {result['error']}")
        
        # Small delay to be nice to Plex
        if not dry_run:
            time.sleep(0.1)
        
        # Batch delay for larger operations
        if i % batch_size == 0 and i < total_albums:
            if not dry_run:
                print(f"   ⏸️  Processed {i} albums. Pausing briefly...")
                time.sleep(1)
    
    return results


def main():
    """Main function."""
    
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print("🧹 Clean Plex Metadata Script")
        print("=" * 50)
        print("Removes invalid metadata from Plex music library:")
        print("• Removes genres/styles not found in rym-genre-tree.json")
        print("• Removes moods not found in rym-descriptor-tree.json")
        print("• Case-insensitive matching")
        print()
        print("Usage:")
        print("  python clean_plex_metadata.py [options]")
        print()
        print("Options:")
        print("  --execute          Actually remove invalid tags (default is dry run)")
        print("  --batch-size N     Process albums in batches of N (default: 50)")
        print("  --limit N          Only process first N albums (for testing)")
        print("  --export-removed   Export details of removed tags to CSV")
        print("  --verbose          Show current tags for albums that are already clean")
        print("  --help, -h         Show this help message")
        return
    
    print("🧹 Clean Plex Metadata Script")
    print("=" * 50)
    
    execute = "--execute" in sys.argv
    export_removed = "--export-removed" in sys.argv
    verbose = "--verbose" in sys.argv
    
    # Parse batch size and limit
    batch_size = 50  # default
    limit = None  # default (no limit)
    
    for i, arg in enumerate(sys.argv):
        if arg == "--batch-size" and i + 1 < len(sys.argv):
            try:
                batch_size = int(sys.argv[i + 1])
                if batch_size < 1:
                    print("❌ Batch size must be at least 1")
                    return
            except ValueError:
                print("❌ Invalid batch size. Must be a number.")
                return
        elif arg == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
                if limit < 1:
                    print("❌ Limit must be at least 1")
                    return
            except ValueError:
                print("❌ Invalid limit. Must be a number.")
                return
    
    if not execute:
        print("🔍 DRY RUN MODE - No changes will be made")
        print("   Use --execute to actually remove invalid tags")
    else:
        print("⚠️  EXECUTE MODE - Invalid tags will be permanently removed")
    
    print()
    
    # Load RYM trees
    print("🌳 Loading RYM genre hierarchy...")
    hierarchy = RYMGenreHierarchy()
    if not hierarchy.all_genres:
        print("❌ Failed to load RYM genre hierarchy")
        return
    
    # Normalize genre names for case-insensitive comparison
    valid_genres = {normalize_tag(genre) for genre in hierarchy.all_genres}
    print(f"✅ Loaded {len(valid_genres)} valid genres from RYM tree")
    
    print("\n📝 Loading RYM descriptor tree...")
    valid_descriptors = load_rym_descriptor_tree()
    if not valid_descriptors:
        print("❌ Failed to load RYM descriptor tree")
        return
    
    # Connect to Plex
    print("\n🔌 Connecting to Plex...")
    plex, music_library = connect_to_plex()
    if not music_library:
        return
    
    # Clean all albums
    results = clean_all_albums(
        music_library, valid_genres, valid_descriptors, 
        dry_run=not execute, batch_size=batch_size, limit=limit, verbose=verbose
    )
    
    if not results:
        return
    
    # Analyze results
    no_changes = sum(1 for r in results if r['status'] == 'no_changes')
    would_clean = sum(1 for r in results if r['status'] == 'would_clean')
    cleaned = sum(1 for r in results if r['status'] == 'cleaned')
    partial_clean = sum(1 for r in results if r['status'] == 'partial_clean')
    errors = sum(1 for r in results if r['status'] == 'error')
    
    # Count total removed tags
    total_removed_tags = 0
    for result in results:
        if result['status'] in ['cleaned', 'partial_clean', 'would_clean'] and result.get('removed_tags'):
            removed = result['removed_tags']
            total_removed_tags += len(removed['genres']) + len(removed['styles']) + len(removed['moods'])
    
    print(f"\n📈 Cleaning Summary:")
    print(f"   Total albums processed: {len(results)}")
    print(f"   No changes needed: {no_changes}")
    
    if execute:
        print(f"   Successfully cleaned: {cleaned}")
        if partial_clean > 0:
            print(f"   Partially cleaned (with warnings): {partial_clean}")
        print(f"   Total invalid tags removed: {total_removed_tags}")
    else:
        print(f"   Would be cleaned: {would_clean}")
        print(f"   Total invalid tags found: {total_removed_tags}")
    
    if errors > 0:
        print(f"   Errors: {errors}")
    
    # Export removed tags if requested
    if export_removed and total_removed_tags > 0:
        export_removed_tags(results)
    
    if not execute and would_clean > 0:
        print(f"\n💡 Found {would_clean} albums with invalid tags")
        print("   Use --execute to actually remove them")
    
    if execute and cleaned > 0:
        print(f"\n💡 Cleaned {cleaned} albums")
        print("   Run 'python review_genres.py' to refresh your cache")


if __name__ == "__main__":
    main()






