#!/usr/bin/env python3
"""
RYM Outdated Albums Updater

Updates genre metadata directly in music files for albums listed in outdated_csv_entries.json
using the newer metadata from rym-scraped.json.

This is a focused version of rym_file_metadata_updater.py that only processes albums
that have been identified as having outdated metadata.

Usage:
    python rym_outdated_updater.py --music-dir /path/to/music --execute
"""

import os
import sys
import json
import csv
import pandas as pd
from pathlib import Path
from collections import Counter
import time
import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

# Import mutagen for audio file metadata
try:
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
    from mutagen.id3 import ID3, TCON, TPE1, TALB, TIT2
except ImportError:
    print("❌ Error: mutagen library not found!")
    print("Install with: pip install mutagen")
    exit(1)

# Import our RYM logic
from rym_genre_hierarchy import RYMGenreHierarchy
from music_directory_cache import MusicDirectoryCache

# File paths
OUTDATED_ENTRIES_FILE = "./outdated_csv_entries.json"
RYM_SCRAPED_FILE = "./data/rym-scraped.json"
RYM_DESCRIPTOR_TREE_FILE = "./data/rym-descriptor-tree.json"

# Import the AudioFileProcessor class from the original updater
from rym_file_metadata_updater import AudioFileProcessor, find_audio_files_direct, group_files_by_album, group_files_by_album_cached
from rym_plex_updater import title_case_tag

class OutdatedAlbumProcessor:
    """Processes albums listed in outdated_csv_entries.json with rym-scraped.json data."""
    
    def __init__(self):
        self.outdated_albums = []
        self.rym_scraped_data = []
        self.matches_found = 0
        self.matches_processed = 0
        self.files_updated = 0
        
    def load_outdated_albums(self) -> bool:
        """Load the list of outdated albums."""
        try:
            with open(OUTDATED_ENTRIES_FILE, 'r', encoding='utf-8') as f:
                self.outdated_albums = json.load(f)
            print(f"📋 Loaded {len(self.outdated_albums)} outdated albums")
            return True
        except FileNotFoundError:
            print(f"❌ File not found: {OUTDATED_ENTRIES_FILE}")
            return False
        except Exception as e:
            print(f"❌ Error loading outdated albums: {e}")
            return False
    
    def load_rym_scraped_data(self) -> bool:
        """Load the scraped RYM data."""
        try:
            with open(RYM_SCRAPED_FILE, 'r', encoding='utf-8') as f:
                self.rym_scraped_data = json.load(f)
            print(f"📊 Loaded {len(self.rym_scraped_data)} RYM scraped entries")
            return True
        except FileNotFoundError:
            print(f"❌ File not found: {RYM_SCRAPED_FILE}")
            return False
        except Exception as e:
            print(f"❌ Error loading RYM scraped data: {e}")
            return False
    
    def find_scraped_match(self, outdated_album: dict) -> Optional[dict]:
        """Find matching entry in scraped data for an outdated album."""
        artist = outdated_album.get('artist', '').strip()
        album = outdated_album.get('album', '').strip()
        
        if not artist or not album:
            return None
        
        # Try exact match first
        for scraped_entry in self.rym_scraped_data:
            scraped_artist = scraped_entry.get('artistName', '').strip()
            scraped_album = scraped_entry.get('releaseTitle', '').strip()
            
            if scraped_artist.lower() == artist.lower() and scraped_album.lower() == album.lower():
                return scraped_entry
        
        # Try fuzzy matching (normalize artist names)
        normalized_artist = self._normalize_artist_name(artist)
        normalized_album = self._normalize_album_name(album)
        
        for scraped_entry in self.rym_scraped_data:
            scraped_artist_norm = self._normalize_artist_name(scraped_entry.get('artistName', ''))
            scraped_album_norm = self._normalize_album_name(scraped_entry.get('releaseTitle', ''))
            
            if scraped_artist_norm == normalized_artist and scraped_album_norm == normalized_album:
                return scraped_entry
        
        return None
    
    def _normalize_artist_name(self, name: str) -> str:
        """Normalize artist names for better matching."""
        if not name:
            return ""
        
        # Remove common prefixes and normalize
        name = name.lower().strip()
        
        # Handle "The " prefix
        if name.startswith("the "):
            name = name[4:]
        
        # Handle parentheses (like "(Sandy) Alex G" -> "sandy alex g")
        name = re.sub(r'\([^)]*\)\s*', '', name)
        
        # Remove extra spaces
        name = re.sub(r'\s+', ' ', name).strip()
        
        return name
    
    def _normalize_album_name(self, name: str) -> str:
        """Normalize album names for better matching."""
        if not name:
            return ""
        
        # Remove common suffixes and normalize
        name = name.lower().strip()
        
        # Remove remaster info, deluxe edition info, etc.
        name = re.sub(r'\s*\(.*?(remaster|deluxe|expanded|edition|bonus).*?\)', '', name, flags=re.IGNORECASE)
        
        # Remove extra spaces
        name = re.sub(r'\s+', ' ', name).strip()
        
        return name
    
    def process_outdated_albums(self, music_dir: Path, hierarchy: RYMGenreHierarchy, 
                              valid_descriptors: set, dry_run: bool = True, 
                              use_cache: bool = True) -> None:
        """Process all outdated albums and update their metadata."""
        
        print(f"\n🔄 Processing {len(self.outdated_albums)} outdated albums...")
        if dry_run:
            print("🔍 DRY RUN MODE - No files will be modified")
        
        # Initialize cache
        cache = None
        if use_cache:
            cache = MusicDirectoryCache()
            if not cache.is_cache_valid(music_dir):
                print("   📁 Building directory cache...")
                processor = AudioFileProcessor()
                cache.build_cache(music_dir, processor.SUPPORTED_EXTENSIONS)
            else:
                cache.load_cache()
        
        # Group outdated albums by Plex artist/album for efficient file finding
        outdated_lookup = {}
        for album in self.outdated_albums:
            plex_artist = album.get('plex_artist', '').strip()
            plex_album = album.get('plex_album', '').strip()
            if plex_artist and plex_album:
                key = f"{plex_artist}|||{plex_album}".lower()
                outdated_lookup[key] = album
        
        print(f"📋 Built lookup table for {len(outdated_lookup)} Plex albums")
        
        # Find audio files and group by album using cache system
        if use_cache and cache:
            # Use cache for everything - no need to find audio files first
            albums = group_files_by_album_cached(cache)
        else:
            print("📁 Scanning for audio files...")
            audio_files = find_audio_files_direct(music_dir, recursive=True)
            albums = group_files_by_album(audio_files)
        
        if not albums:
            print("❌ No albums found with proper metadata")
            return
        
        print(f"📊 Found {len(albums)} albums in music directory")
        
        # Process only the albums that are in our outdated list
        processor = AudioFileProcessor()
        albums_found = 0
        albums_updated = 0
        
        for album_key, album_info in albums.items():
            # Check if this album is in our outdated list
            if album_key not in outdated_lookup:
                continue
            
            albums_found += 1
            outdated_album = outdated_lookup[album_key]
            
            artist = album_info['artist']
            album_title = album_info['album']
            files = album_info['files']
            
            print(f"\n[{albums_found}] {artist} - {album_title} ({len(files)} files)")
            print(f"   🔍 Found in outdated list: {outdated_album.get('artist')} - {outdated_album.get('album')}")
            
            # Find matching scraped data
            scraped_match = self.find_scraped_match(outdated_album)
            
            if scraped_match:
                self.matches_found += 1
                print(f"   ✅ Found updated data: {scraped_match.get('artistName')} - {scraped_match.get('releaseTitle')}")
                
                # Process the scraped data into metadata
                genres_set, groupings_set, styles_set, moods_set = self.process_scraped_data_for_files(
                    scraped_match, hierarchy, valid_descriptors
                )
                
                # Convert to sorted lists
                genres = sorted(list(genres_set))
                groupings = sorted(list(groupings_set))
                styles = sorted(list(styles_set))
                moods = sorted(list(moods_set))
                
                print(f"   📊 Processed: {len(genres)} genres, {len(groupings)} groupings, {len(styles)} styles, {len(moods)} moods")
                
                # Update all files in the album
                album_updated = False
                for file_path in files:
                    success = processor.update_file_metadata(file_path, genres, groupings, styles, moods, dry_run)
                    if success:
                        album_updated = True
                        if not dry_run:
                            self.files_updated += 1
                    
                    # Small delay between files
                    if not dry_run:
                        time.sleep(0.05)
                
                if album_updated:
                    albums_updated += 1
                    self.matches_processed += 1
            else:
                print(f"   ❌ No matching data found in rym-scraped.json")
        
        # Summary
        print(f"\n📈 Processing Summary:")
        print(f"   Total outdated albums in list: {len(self.outdated_albums)}")
        print(f"   Outdated albums found in music directory: {albums_found}")
        print(f"   Albums with updated RYM data: {self.matches_found}")
        print(f"   Albums updated: {albums_updated}")
        print(f"   Files updated: {self.files_updated}")
        
        if dry_run:
            print(f"\n💡 Run with --execute to actually update files")
    
    def process_scraped_data_for_files(self, scraped_data: dict, hierarchy: RYMGenreHierarchy, 
                                     valid_descriptors: set = None) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
        """Process scraped RYM data into genres, styles, moods, and groupings for file metadata."""
        actual_genres = set()
        parent_genres = set()
        styles = set()
        moods = set()
        
        # Process primary genres
        primary_genres = scraped_data.get('genres', [])
        if primary_genres:
            # Clean and add actual genres
            for genre in primary_genres:
                genre_clean = genre.strip()
                if genre_clean:
                    actual_genres.add(title_case_tag(genre_clean))
            
            # Get hierarchical expansion but separate actual from parent genres
            if primary_genres:
                expanded_genres = hierarchy.expand_genres_hierarchically(primary_genres)
                
                # Separate actual RYM genres from parent genres
                for expanded_genre in expanded_genres:
                    if expanded_genre in primary_genres:
                        # This is an actual RYM genre, already in actual_genres
                        continue
                    else:
                        # This is a parent genre from hierarchical expansion
                        parent_genres.add(expanded_genre)
        
        # Process secondary genres (add as styles)
        secondary_genres = scraped_data.get('secondaryGenres', [])
        if secondary_genres:
            for genre in secondary_genres:
                genre_clean = genre.strip()
                if genre_clean:
                    styles.add(title_case_tag(genre_clean))
        
        # Process descriptors as moods with correction
        descriptors = scraped_data.get('descriptors', [])
        if descriptors:
            for descriptor in descriptors:
                descriptor_clean = descriptor.strip()
                if descriptor_clean:
                    # Use descriptor correction if valid descriptors are available
                    if valid_descriptors:
                        corrected_descriptor = correct_descriptor_name(descriptor_clean, valid_descriptors)
                        if corrected_descriptor:  # Only add if correction was successful
                            moods.add(corrected_descriptor)
                    else:
                        # Fallback to basic processing
                        if descriptor_clean.lower() == 'male vocalist':
                            moods.add("Male Vocalist")
                        elif descriptor_clean.lower() == 'female vocalist':
                            moods.add("Female Vocalist")
                        elif descriptor_clean.lower() == 'androgynous vocals':
                            moods.add("Androgynous Vocals")
                        else:
                            moods.add(title_case_tag(descriptor_clean))
        
        return actual_genres, parent_genres, styles, moods

def load_rym_descriptor_tree() -> set:
    """Load valid descriptors from the RYM descriptor tree."""
    try:
        with open(RYM_DESCRIPTOR_TREE_FILE, 'r', encoding='utf-8') as f:
            descriptor_tree = json.load(f)
        
        valid_descriptors = set()
        
        def extract_descriptors(node):
            if isinstance(node, dict):
                if 'name' in node:
                    valid_descriptors.add(node['name'])
                if 'children' in node:
                    for child in node['children']:
                        extract_descriptors(child)
        
        extract_descriptors(descriptor_tree)
        print(f"📝 Loaded {len(valid_descriptors)} valid descriptors")
        return valid_descriptors
        
    except Exception as e:
        print(f"⚠️  Error loading descriptor tree: {e}")
        return set()

def correct_descriptor_name(descriptor: str, valid_descriptors: set) -> Optional[str]:
    """Correct descriptor name using the valid descriptors set."""
    if not descriptor or not valid_descriptors:
        return None
    
    # Try exact match first (case insensitive)
    for valid_desc in valid_descriptors:
        if descriptor.lower() == valid_desc.lower():
            return valid_desc
    
    # Try special mappings
    special_mappings = {
        'malevocals': 'male vocalist',
        'femalevocals': 'female vocalist',
        'androgynousvocals': 'androgynous vocals'
    }
    
    desc_lower = descriptor.lower()
    if desc_lower in special_mappings:
        mapped_desc = special_mappings[desc_lower]
        # Find the correct case version
        for valid_desc in valid_descriptors:
            if mapped_desc.lower() == valid_desc.lower():
                return valid_desc
    
    return None

def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Update audio file metadata for outdated albums using rym-scraped.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be updated
  python rym_outdated_updater.py --music-dir /path/to/music
  
  # Actually update files
  python rym_outdated_updater.py --music-dir /path/to/music --execute
  
  # Disable cache (use direct scanning)
  python rym_outdated_updater.py --music-dir /path/to/music --no-cache --execute

Notes:
  • This script only processes albums listed in outdated_csv_entries.json
  • It matches them with newer metadata from rym-scraped.json
  • The matching is done by artist and album name (with normalization)
  • Albums are matched using their plex_artist and plex_album fields
  • Directory cache speeds up processing on large libraries
        """
    )
    
    parser.add_argument(
        '--music-dir', 
        required=True, 
        help='Path to music directory to scan'
    )
    parser.add_argument(
        '--execute', 
        action='store_true', 
        help='Actually update files (default is dry run)'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable directory caching (use direct scanning)'
    )
    
    args = parser.parse_args()
    
    print("🎵 RYM Outdated Albums Updater")
    print("=" * 50)
    
    # Initialize processor
    processor = OutdatedAlbumProcessor()
    
    # Load required data
    if not processor.load_outdated_albums():
        return
    
    if not processor.load_rym_scraped_data():
        return
    
    # Initialize RYM processing
    print("🌳 Loading RYM genre hierarchy...")
    hierarchy = RYMGenreHierarchy()
    if not hierarchy.all_genres:
        print("❌ Failed to load RYM genre hierarchy")
        return
    
    print("📝 Loading RYM descriptor tree...")
    valid_descriptors = load_rym_descriptor_tree()
    
    # Process outdated albums
    music_path = Path(args.music_dir)
    if not music_path.exists():
        print(f"❌ Music directory does not exist: {args.music_dir}")
        return
    
    processor.process_outdated_albums(
        music_dir=music_path,
        hierarchy=hierarchy,
        valid_descriptors=valid_descriptors,
        dry_run=not args.execute,
        use_cache=not args.no_cache
    )

if __name__ == "__main__":
    main() 