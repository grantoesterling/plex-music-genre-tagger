#!/usr/bin/env python3
"""
RYM File Metadata Updater

Updates genre metadata directly in music files (FLAC, MP3, etc.) using RYM data.
Uses mutagen to write metadata tags directly to audio files.

Usage:
    python rym_file_metadata_updater.py --music-dir /path/to/music --execute
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
RYM_CSV_FILE = "./data/rym.csv"
RYM_JSON_FILE = "./data/rym-scraped.json"
RYM_MANUAL_FILE = "./data/rym-manual.json"
RYM_DESCRIPTOR_TREE_FILE = "./data/rym-descriptor-tree.json"

# Import RYM processing functions from the Plex updater
exec(open('rym_plex_updater.py').read().split('def main():')[0])

class AudioFileProcessor:
    """Handles reading and writing metadata for various audio file formats."""
    
    SUPPORTED_EXTENSIONS = {'.flac', '.mp3', '.m4a', '.ogg', '.opus'}
    
    def __init__(self):
        self.files_processed = 0
        self.files_updated = 0
        self.files_skipped = 0
        self.files_errors = 0
    
    def is_supported_file(self, filepath: Path) -> bool:
        """Check if file is a supported audio format."""
        return filepath.suffix.lower() in self.SUPPORTED_EXTENSIONS
    
    def get_file_metadata(self, filepath: Path) -> dict:
        """Extract metadata from audio file."""
        try:
            audiofile = mutagen.File(filepath)
            if audiofile is None:
                return None
            
            # Extract basic metadata
            metadata = {
                'filepath': str(filepath),
                'artist': self._get_tag_value(audiofile, 'artist'),
                'album': self._get_tag_value(audiofile, 'album'),
                'title': self._get_tag_value(audiofile, 'title'),
                'genre': self._get_tag_value(audiofile, 'genre', is_list=True),
                'format': filepath.suffix.lower()[1:],  # Remove the dot
                'audiofile': audiofile  # Keep reference for updating
            }
            
            return metadata
            
        except Exception as e:
            print(f"   ❌ Error reading {filepath.name}: {e}")
            return None
    
    def _get_tag_value(self, audiofile, tag_name: str, is_list: bool = False):
        """Get tag value from audio file, handling different formats."""
        value = None
        
        if isinstance(audiofile, FLAC):
            tag_map = {
                'artist': 'ARTIST',
                'album': 'ALBUM', 
                'title': 'TITLE',
                'genre': 'GENRE'
            }
            flac_tag = tag_map.get(tag_name)
            if flac_tag and flac_tag in audiofile:
                value = audiofile[flac_tag]
                
        elif isinstance(audiofile, MP3):
            if audiofile.tags:
                tag_map = {
                    'artist': 'TPE1',
                    'album': 'TALB',
                    'title': 'TIT2', 
                    'genre': 'TCON'
                }
                id3_tag = tag_map.get(tag_name)
                if id3_tag and id3_tag in audiofile.tags:
                    value = audiofile.tags[id3_tag].text
                    
        elif isinstance(audiofile, MP4):
            tag_map = {
                'artist': '\xa9ART',
                'album': '\xa9alb',
                'title': '\xa9nam',
                'genre': '\xa9gen'
            }
            mp4_tag = tag_map.get(tag_name)
            if mp4_tag and mp4_tag in audiofile:
                value = audiofile[mp4_tag]
                
        elif isinstance(audiofile, OggVorbis):
            tag_map = {
                'artist': 'ARTIST',
                'album': 'ALBUM',
                'title': 'TITLE', 
                'genre': 'GENRE'
            }
            ogg_tag = tag_map.get(tag_name)
            if ogg_tag and ogg_tag in audiofile:
                value = audiofile[ogg_tag]
        
        # Handle value formatting
        if value:
            if is_list:
                if isinstance(value, list):
                    return [str(v) for v in value]
                else:
                    # Split on common delimiters for genre lists
                    value_str = str(value)
                    if ';' in value_str:
                        return [g.strip() for g in value_str.split(';')]
                    elif ',' in value_str:
                        return [g.strip() for g in value_str.split(',')]
                    else:
                        return [value_str]
            else:
                return str(value) if not isinstance(value, list) else str(value[0])
        
        return [] if is_list else None
    
    def get_complete_file_metadata(self, filepath: Path) -> dict:
        """Extract complete metadata from audio file including groupings, styles, and moods."""
        try:
            audiofile = mutagen.File(filepath)
            if audiofile is None:
                return None
            
            # Extract complete metadata
            metadata = {
                'filepath': str(filepath),
                'artist': self._get_tag_value(audiofile, 'artist'),
                'album': self._get_tag_value(audiofile, 'album'),
                'title': self._get_tag_value(audiofile, 'title'),
                'genre': self._get_tag_value(audiofile, 'genre', is_list=True),
                'groupings': self._get_extended_tag_value(audiofile, 'groupings', is_list=True),
                'styles': self._get_extended_tag_value(audiofile, 'styles', is_list=True),
                'moods': self._get_extended_tag_value(audiofile, 'moods', is_list=True),
                'format': filepath.suffix.lower()[1:],  # Remove the dot
                'audiofile': audiofile  # Keep reference for updating
            }
            
            return metadata
            
        except Exception as e:
            print(f"   ❌ Error reading {filepath.name}: {e}")
            return None
    
    def _get_extended_tag_value(self, audiofile, tag_name: str, is_list: bool = False):
        """Get extended tag values (groupings, styles, moods) from audio file, handling different formats."""
        value = None
        
        if isinstance(audiofile, FLAC):
            tag_map = {
                'groupings': 'GROUPINGS',
                'styles': 'STYLE',
                'moods': 'MOOD'
            }
            flac_tag = tag_map.get(tag_name)
            if flac_tag and flac_tag in audiofile:
                value = audiofile[flac_tag]
                
        elif isinstance(audiofile, MP3):
            if audiofile.tags:
                tag_map = {
                    'groupings': 'TXXX:GROUPING',
                    'styles': 'TXXX:STYLE',
                    'moods': 'TXXX:MOOD'
                }
                id3_tag = tag_map.get(tag_name)
                if id3_tag and id3_tag in audiofile.tags:
                    value = audiofile.tags[id3_tag].text
                    
        elif isinstance(audiofile, MP4):
            tag_map = {
                'groupings': '----:com.apple.iTunes:GROUPING',
                'styles': '----:com.apple.iTunes:STYLE',
                'moods': '----:com.apple.iTunes:MOOD'
            }
            mp4_tag = tag_map.get(tag_name)
            if mp4_tag and mp4_tag in audiofile:
                # MP4 custom tags are byte strings
                raw_value = audiofile[mp4_tag]
                if isinstance(raw_value, list):
                    value = [v.decode('utf-8') if isinstance(v, bytes) else str(v) for v in raw_value]
                else:
                    value = raw_value.decode('utf-8') if isinstance(raw_value, bytes) else str(raw_value)
                    
        elif isinstance(audiofile, OggVorbis):
            tag_map = {
                'groupings': 'GROUPINGS',
                'styles': 'STYLE',
                'moods': 'MOOD'
            }
            ogg_tag = tag_map.get(tag_name)
            if ogg_tag and ogg_tag in audiofile:
                value = audiofile[ogg_tag]
        
        # Handle value formatting
        if value:
            if is_list:
                if isinstance(value, list):
                    return [str(v) for v in value]
                else:
                    # Split on common delimiters for lists
                    value_str = str(value)
                    if ';' in value_str:
                        return [g.strip() for g in value_str.split(';')]
                    elif ',' in value_str:
                        return [g.strip() for g in value_str.split(',')]
                    else:
                        return [value_str]
            else:
                return str(value) if not isinstance(value, list) else str(value[0])
        
        return [] if is_list else None
    
    def update_file_metadata(self, filepath: Path, genres: list, groupings: list, styles: list, moods: list, dry_run: bool = True):
        """Update audio file with new metadata."""
        try:
            if dry_run:
                print(f"   🔍 DRY RUN - Would update {filepath.name}")
                print(f"      Set GENRE: {genres[:3]}{'...' if len(genres) > 3 else ''}")
                if groupings:
                    print(f"      Set GROUPING: {groupings[:3]}{'...' if len(groupings) > 3 else ''}")
                if styles:
                    print(f"      Set STYLE: {styles[:3]}{'...' if len(styles) > 3 else ''}")
                if moods:
                    print(f"      Set MOOD: {moods[:3]}{'...' if len(moods) > 3 else ''}")
                return True
            
            audiofile = mutagen.File(filepath)
            if audiofile is None:
                print(f"   ❌ Cannot write to {filepath.name}: Unsupported format")
                return False
            
            # Update metadata based on file format
            success = False
            
            if isinstance(audiofile, FLAC):
                success = self._update_flac_metadata(audiofile, genres, groupings, styles, moods)
            elif isinstance(audiofile, MP3):
                success = self._update_mp3_metadata(audiofile, genres, groupings, styles, moods)
            elif isinstance(audiofile, MP4):
                success = self._update_mp4_metadata(audiofile, genres, groupings, styles, moods)
            elif isinstance(audiofile, OggVorbis):
                success = self._update_ogg_metadata(audiofile, genres, groupings, styles, moods)
            else:
                print(f"   ❌ Unsupported format: {type(audiofile)}")
                return False
            
            if success:
                audiofile.save()
                print(f"   ✅ Updated {filepath.name}")
                print(f"      Set {len(genres)} genres, {len(groupings)} groupings, {len(styles)} styles, {len(moods)} moods")
                return True
            else:
                print(f"   ❌ Failed to update {filepath.name}")
                return False
                
        except Exception as e:
            print(f"   ❌ Error updating {filepath.name}: {e}")
            return False
    
    def _update_flac_metadata(self, audiofile: FLAC, genres: list, groupings: list, styles: list, moods: list):
        """Update FLAC metadata."""
        try:
            # Clear existing tags
            for tag in ['GENRE', 'GROUPINGS', 'STYLE', 'MOOD']:
                if tag in audiofile:
                    del audiofile[tag]
            
            # Set new metadata
            if genres:
                audiofile['GENRE'] = genres
            if groupings:
                audiofile['GROUPINGS'] = groupings
            if styles:
                audiofile['STYLE'] = styles  
            if moods:
                audiofile['MOOD'] = moods
                
            return True
        except Exception as e:
            print(f"      Error updating FLAC: {e}")
            return False
    
    def _update_mp3_metadata(self, audiofile: MP3, genres: list, groupings: list, styles: list, moods: list):
        """Update MP3 ID3 metadata."""
        try:
            # Ensure ID3 tags exist
            if audiofile.tags is None:
                audiofile.add_tags()
            
            # Clear existing genre tags
            if 'TCON' in audiofile.tags:
                del audiofile.tags['TCON']
            
            # Set genres (ID3 supports multiple values)
            if genres:
                audiofile.tags['TCON'] = TCON(encoding=3, text=genres)
            
            # For groupings, styles and moods, use custom frames (TXXX)
            # Note: Not all players support these custom fields
            from mutagen.id3 import TXXX
            
            # Clear existing custom tags
            for frame_id in list(audiofile.tags.keys()):
                if frame_id.startswith('TXXX:GROUPING') or frame_id.startswith('TXXX:STYLE') or frame_id.startswith('TXXX:MOOD'):
                    del audiofile.tags[frame_id]
            
            if groupings:
                audiofile.tags['TXXX:GROUPING'] = TXXX(encoding=3, desc='GROUPING', text=groupings)
            if styles:
                audiofile.tags['TXXX:STYLE'] = TXXX(encoding=3, desc='STYLE', text=styles)
            if moods:
                audiofile.tags['TXXX:MOOD'] = TXXX(encoding=3, desc='MOOD', text=moods)
                
            return True
        except Exception as e:
            print(f"      Error updating MP3: {e}")
            return False
    
    def _update_mp4_metadata(self, audiofile: MP4, genres: list, groupings: list, styles: list, moods: list):
        """Update MP4 metadata."""
        try:
            # Set genres (standard field)
            if genres:
                audiofile['\xa9gen'] = genres
            elif '\xa9gen' in audiofile:
                del audiofile['\xa9gen']
            
            # Use custom fields for groupings, styles and moods
            if groupings:
                audiofile['----:com.apple.iTunes:GROUPING'] = [g.encode('utf-8') for g in groupings]
            elif '----:com.apple.iTunes:GROUPING' in audiofile:
                del audiofile['----:com.apple.iTunes:GROUPING']
                
            if styles:
                audiofile['----:com.apple.iTunes:STYLE'] = [s.encode('utf-8') for s in styles]
            elif '----:com.apple.iTunes:STYLE' in audiofile:
                del audiofile['----:com.apple.iTunes:STYLE']
                
            if moods:
                audiofile['----:com.apple.iTunes:MOOD'] = [m.encode('utf-8') for m in moods]
            elif '----:com.apple.iTunes:MOOD' in audiofile:
                del audiofile['----:com.apple.iTunes:MOOD']
                
            return True
        except Exception as e:
            print(f"      Error updating MP4: {e}")
            return False
    
    def _update_ogg_metadata(self, audiofile: OggVorbis, genres: list, groupings: list, styles: list, moods: list):
        """Update OGG Vorbis metadata."""
        try:
            # Clear existing tags
            for tag in ['GENRE', 'GROUPINGS', 'STYLE', 'MOOD']:
                if tag in audiofile:
                    del audiofile[tag]
            
            # Set new metadata
            if genres:
                audiofile['GENRE'] = genres
            if groupings:
                audiofile['GROUPINGS'] = groupings
            if styles:
                audiofile['STYLE'] = styles
            if moods:
                audiofile['MOOD'] = moods
                
            return True
        except Exception as e:
            print(f"      Error updating OGG: {e}")
            return False

def find_audio_files_cached(music_dir: Path, recursive: bool = True, sample_artists: int = None, use_cache: bool = True) -> list:
    """Find all supported audio files using directory cache for speed."""
    processor = AudioFileProcessor()
    
    print(f"🔍 Finding audio files in: {music_dir}")
    
    if use_cache:
        # Use cache system
        cache = MusicDirectoryCache()
        
        # Check if cache is valid, build if needed
        if not cache.is_cache_valid(music_dir):
            print("   📁 Building directory cache (first time or cache expired)...")
            cache.build_cache(music_dir, processor.SUPPORTED_EXTENSIONS)
        else:
            cache.load_cache()
        
        # Smart sampling using cache
        if sample_artists and recursive:
            print(f"🧪 Smart sampling mode: Will sample from {sample_artists} random artists (using cache)")
            
            # Get random artists from cache
            sampled_artists = cache.get_random_artists(sample_artists)
            
            print(f"   🎲 Selected {len(sampled_artists)} artists from cache:")
            for i, artist_dir in enumerate(sampled_artists, 1):
                print(f"   [{i}/{len(sampled_artists)}] {artist_dir.name}")
            
            # Get all files for the sampled artists
            artist_names = [artist_dir.name for artist_dir in sampled_artists]
            audio_files = cache.get_files_for_artists(artist_names)
            
            print(f"📊 Cache-based sampling found {len(audio_files)} audio files from {len(sampled_artists)} artists")
            
        else:
            # Get all files from cache
            if recursive:
                print("   📁 Getting all files from cache...")
                audio_files = cache.get_all_files()
            else:
                # For non-recursive, we'd need to implement top-level only logic
                print("   ⚠️  Non-recursive mode not supported with cache, falling back to direct scan")
                return find_audio_files_direct(music_dir, recursive, sample_artists)
            
            print(f"📊 Cache found {len(audio_files)} supported audio files")
    
    else:
        # Fallback to direct scanning
        return find_audio_files_direct(music_dir, recursive, sample_artists)
    
    return audio_files

def find_audio_files_direct(music_dir: Path, recursive: bool = True, sample_artists: int = None) -> list:
    """Original direct scanning method (fallback when cache is disabled)."""
    processor = AudioFileProcessor()
    audio_files = []
    
    print(f"🔍 Scanning for audio files in: {music_dir} (direct mode)")
    
    # Smart sampling: if sample_artists is specified, sample artists first
    if sample_artists and recursive:
        print(f"🧪 Smart sampling mode: Will sample from {sample_artists} random artists")
        print("   📁 Getting list of artist directories...")
        
        # Get artist directories (first level only)
        artist_dirs = []
        try:
            for item in music_dir.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    artist_dirs.append(item)
        except Exception as e:
            print(f"   ❌ Error reading directory: {e}")
            return []
        
        print(f"   Found {len(artist_dirs)} artist directories")
        
        # Sample the requested number of artists
        artists_to_sample = min(sample_artists, len(artist_dirs))
        print(f"   🎲 Sampling {artists_to_sample} random artists...")
        
        # Randomly sample artists
        import random
        sampled_artists = random.sample(artist_dirs, artists_to_sample)
        
        # Now scan only the sampled artists
        for i, artist_dir in enumerate(sampled_artists, 1):
            print(f"   [{i}/{len(sampled_artists)}] Scanning: {artist_dir.name}")
            
            try:
                for filepath in artist_dir.rglob("*"):
                    if filepath.is_file() and processor.is_supported_file(filepath):
                        audio_files.append(filepath)
                        
            except Exception as e:
                print(f"      ⚠️  Error scanning {artist_dir.name}: {e}")
                continue
        
        print(f"📊 Smart sampling found {len(audio_files)} audio files from {len(sampled_artists)} artists")
        
    else:
        # Original full scan approach
        if recursive:
            print("   Scanning recursively through all subdirectories...")
        else:
            print("   Scanning only the top-level directory...")
        
        pattern = "**/*" if recursive else "*"
        
        # Count directories first for better progress estimation (only for full scans)
        total_dirs = 0
        dirs_processed = 0
        
        if recursive:
            print("   📊 Counting directories...")
            try:
                for i, path in enumerate(music_dir.rglob("*")):
                    if path.is_dir():
                        total_dirs += 1
                    # Show progress every 500 items during counting
                    if i % 500 == 0 and i > 0:
                        print(f"      Counting progress: {i} items scanned, {total_dirs} directories found...")
                print(f"   Found {total_dirs} directories to scan")
            except Exception as e:
                print(f"   ⚠️  Error during directory counting: {e}")
                total_dirs = 0
        
        # Now scan for files with progress
        try:
            for i, filepath in enumerate(music_dir.glob(pattern)):
                # Update progress every 100 items for performance
                if i % 100 == 0 and i > 0:
                    print(f"   Progress: Scanned {i} items, found {len(audio_files)} audio files...")
                
                # Track directory progress for recursive scans
                if recursive and filepath.is_dir():
                    dirs_processed += 1
                    if dirs_processed % 50 == 0 and total_dirs > 0:
                        percentage = (dirs_processed / total_dirs * 100)
                        print(f"   Directory progress: {dirs_processed}/{total_dirs} ({percentage:.1f}%)")
                
                if filepath.is_file() and processor.is_supported_file(filepath):
                    audio_files.append(filepath)
                    
        except Exception as e:
            print(f"   ❌ Error during file scanning: {e}")
            return []
        
        print(f"📊 Found {len(audio_files)} supported audio files")
    
    return audio_files

def group_files_by_album_cached(cache: MusicDirectoryCache, audio_files: list = None) -> dict:
    """Group audio files by album using cached metadata (much faster)."""
    if cache.cache_data and 'files_metadata' in cache.cache_data:
        print("📋 Using cached metadata for album grouping...")
        return cache.get_albums_from_cache()
    else:
        print("⚠️  No cached metadata available, falling back to direct file reading...")
        return group_files_by_album(audio_files or [])

def group_files_by_album(audio_files: list) -> dict:
    """Group audio files by album for batch processing (fallback method)."""
    processor = AudioFileProcessor()
    albums = {}
    
    print("📋 Grouping files by album (reading file metadata)...")
    
    files_processed = 0
    for filepath in audio_files:
        files_processed += 1
        
        # Show progress every 100 files
        if files_processed % 100 == 0:
            print(f"   Progress: Processed {files_processed}/{len(audio_files)} files, found {len(albums)} albums...")
        
        try:
            metadata = processor.get_file_metadata(filepath)
            if metadata and metadata['artist'] and metadata['album']:
                album_key = f"{metadata['artist']}|||{metadata['album']}".lower()
                
                if album_key not in albums:
                    albums[album_key] = {
                        'artist': metadata['artist'],
                        'album': metadata['album'],
                        'files': []
                    }
                
                albums[album_key]['files'].append(filepath)
        except Exception as e:
            print(f"      ⚠️  Error processing {filepath.name}: {e}")
            continue
    
    print(f"📊 Grouped {len(audio_files)} files into {len(albums)} albums")
    return albums

def update_audio_files(music_dir: str, dry_run: bool = True, recursive: bool = True, limit: int = None, sample_artists: int = None, use_cache: bool = True, refresh_cache: bool = False, force_update: bool = False):
    """Main function to update audio file metadata."""
    music_path = Path(music_dir)
    
    if not music_path.exists():
        print(f"❌ Music directory does not exist: {music_dir}")
        return
    
    # Initialize cache object
    cache = None
    if use_cache:
        cache = MusicDirectoryCache()
        
        # Handle cache refresh if requested
        if refresh_cache:
            print("🔄 Forcing cache refresh...")
            processor = AudioFileProcessor()
            cache.build_cache(music_path, processor.SUPPORTED_EXTENSIONS)
        elif not cache.is_cache_valid(music_path):
            print("   📁 Building directory cache (first time or cache expired)...")
            processor = AudioFileProcessor()
            cache.build_cache(music_path, processor.SUPPORTED_EXTENSIONS)
        else:
            cache.load_cache()
    
    # Initialize RYM processing
    print("🌳 Loading RYM genre hierarchy...")
    hierarchy = RYMGenreHierarchy()
    if not hierarchy.all_genres:
        print("❌ Failed to load RYM genre hierarchy")
        return
    
    print("📝 Loading RYM descriptor tree...")
    valid_descriptors = load_rym_descriptor_tree()
    
    print("📊 Loading RYM data...")
    rym_data = load_rym_data()
    if rym_data is None:
        print("❌ Failed to load RYM data")
        return
    
    # Find and group audio files with cache support
    if use_cache and cache:
        # Use cache for everything
        audio_files = find_audio_files_cached(music_path, recursive, sample_artists, use_cache)
        if not audio_files:
            print("❌ No supported audio files found")
            return
        
        # Use cached metadata for grouping (much faster)
        albums = group_files_by_album_cached(cache, audio_files)
    else:
        # Fallback to direct scanning
        audio_files = find_audio_files_cached(music_path, recursive, sample_artists, use_cache=False)
        if not audio_files:
            print("❌ No supported audio files found")
            return
        
        albums = group_files_by_album(audio_files)
    
    if not albums:
        print("❌ No albums found with proper metadata")
        return
    
    # Apply limit for testing (limit albums, not artists)
    if limit:
        album_items = list(albums.items())[:limit]
        albums = dict(album_items)
        print(f"🧪 Album limit: Processing first {len(albums)} albums (--limit {limit})")
    
    # Process albums
    processor = AudioFileProcessor()
    
    print(f"\n🔄 Processing {len(albums)} albums...")
    if dry_run:
        print("🔍 DRY RUN MODE - No files will be modified")
    if not force_update:
        print("📋 SKIP MODE - Albums with matching RYM metadata will be skipped (use --force to override)")
    
    matched_albums = 0
    updated_albums = 0
    skipped_albums = 0
    
    for i, (album_key, album_info) in enumerate(albums.items(), 1):
        artist = album_info['artist']
        album_title = album_info['album']
        files = album_info['files']
        
        print(f"\n[{i}/{len(albums)}] {artist} - {album_title} ({len(files)} files)")
        
        # Find RYM match
        rym_match = find_rym_match(artist, album_title, rym_data)
        
        if rym_match:
            match_type = rym_match.get('match_type', 'unknown')
            
            if match_type == 'exact':
                print(f"   ✅ Found exact match in RYM data")
            elif match_type == 'fuzzy':
                similarity = rym_match.get('similarity_score', 0)
                print(f"   ✅ Found fuzzy match in RYM data (similarity: {similarity:.2f})")
            elif match_type == 'album_only':
                print(f"   ✅ Found album-only match: {rym_match.get('artist_name', '')} - {rym_match.get('release_name', '')}")
            
            # Process RYM data
            genres_set, groupings_set, styles_set, moods_set = process_rym_genres_for_files(rym_match, hierarchy, valid_descriptors)
            
            # Convert to sorted lists
            genres = sorted(list(genres_set))
            groupings = sorted(list(groupings_set))
            styles = sorted(list(styles_set)) 
            moods = sorted(list(moods_set))
            
            print(f"   📊 Processed: {len(genres)} genres, {len(groupings)} groupings, {len(styles)} styles, {len(moods)} moods")
            
            matched_albums += 1
            
            # Check if album already has matching RYM metadata (unless force_update is True)
            if not force_update and album_already_has_rym_metadata(files, genres, groupings, styles, moods):
                print(f"   ⏭️  Album already has matching RYM metadata - skipping")
                skipped_albums += 1
                continue
            
            # Update all files in the album
            album_updated = False
            for file_path in files:
                success = processor.update_file_metadata(file_path, genres, groupings, styles, moods, dry_run)
                if success:
                    album_updated = True
                
                # Small delay between files
                if not dry_run:
                    time.sleep(0.05)
            
            if album_updated:
                updated_albums += 1
        else:
            print(f"   ❌ Not found in RYM data")
    
    # Summary
    print(f"\n📈 Processing Summary:")
    print(f"   Total albums processed: {len(albums)}")
    print(f"   Albums found in RYM: {matched_albums}")
    print(f"   Albums skipped (already have RYM metadata): {skipped_albums}")
    print(f"   Albums updated: {updated_albums}")
    
    if dry_run:
        print(f"\n💡 Run with --execute to actually update files")
    if skipped_albums > 0 and not force_update:
        print(f"💡 Run with --force to update albums that already have RYM metadata")

def process_rym_genres_for_files(rym_match: dict, hierarchy: RYMGenreHierarchy, valid_descriptors: set = None):
    """Process RYM data into genres, styles, moods, and groupings for file metadata.
    
    Unlike the Plex version, this separates:
    - genres: Only the actual RYM genres (no hierarchical expansion)
    - groupings: Parent genres from hierarchical expansion
    - styles: Secondary genres (no expansion)
    - moods: Descriptors (with correction)
    """
    actual_genres = set()
    parent_genres = set()
    styles = set()
    moods = set()
    
    # Process primary genres
    if pd.notna(rym_match.get('primary_genres')) and rym_match['primary_genres']:
        primary_genres_str = str(rym_match['primary_genres']).strip()
        if primary_genres_str.upper() != 'NA':
            primary_genres = [genre.strip() for genre in primary_genres_str.split(',')]
            primary_genres = [title_case_tag(genre) for genre in primary_genres if genre and genre.upper() != 'NA']
            
            # Add actual genres to genres set
            for genre in primary_genres:
                actual_genres.add(genre)
            
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
    
    # Process secondary genres (no expansion, just add as styles)
    if pd.notna(rym_match.get('secondary_genres')) and rym_match['secondary_genres']:
        secondary_genres_str = str(rym_match['secondary_genres']).strip()
        if secondary_genres_str.upper() != 'NA':
            secondary_genres = [genre.strip() for genre in secondary_genres_str.split(',')]
            for genre in secondary_genres:
                genre_clean = genre.strip()
                if genre_clean and genre_clean.upper() != 'NA':
                    styles.add(title_case_tag(genre_clean))
    
    # Process descriptors as moods with correction
    if pd.notna(rym_match.get('descriptors')) and rym_match['descriptors']:
        descriptors_str = str(rym_match['descriptors']).strip()
        if descriptors_str.upper() != 'NA':
            descriptors = [descriptor.strip() for descriptor in descriptors_str.split(',')]
            for descriptor in descriptors:
                descriptor_clean = descriptor.strip()
                if descriptor_clean and descriptor_clean.upper() != 'NA':
                    # Use descriptor correction if valid descriptors are available
                    if valid_descriptors:
                        corrected_descriptor = correct_descriptor_name(descriptor_clean, valid_descriptors)
                        if corrected_descriptor:  # Only add if correction was successful
                            moods.add(corrected_descriptor)
                    else:
                        # Fallback to old logic if no descriptor tree available
                        if descriptor_clean.lower() == 'malevocals':
                            moods.add("Male Vocalist")
                        elif descriptor_clean.lower() == 'femalevocals':
                            moods.add("Female Vocalist")
                        elif descriptor_clean.lower() == 'androgynousvocals':
                            moods.add("Androgynous Vocals")
                        else:
                            moods.add(title_case_tag(descriptor_clean))
    
    # Add rating tags to styles
    if pd.notna(rym_match.get('avg_rating')):
        rating = float(rym_match['avg_rating'])
        if rating >= 4.0:
            styles.add("RYM Average Rating: 4+")
        elif rating >= 3.8:
            styles.add("RYM Average Rating: 3.8+")
    
    return actual_genres, parent_genres, styles, moods

def album_already_has_rym_metadata(album_files: list, rym_genres: list, rym_groupings: list, rym_styles: list, rym_moods: list, tolerance: float = 0.9) -> bool:
    """
    Check if an album already has matching RYM metadata.
    
    Args:
        album_files: List of file paths in the album
        rym_genres: Genres from RYM data
        rym_groupings: Groupings from RYM data  
        rym_styles: Styles from RYM data
        rym_moods: Moods from RYM data
        tolerance: Minimum similarity ratio to consider a match (0.0-1.0)
    
    Returns:
        True if the album already has matching metadata, False otherwise
    """
    processor = AudioFileProcessor()
    
    # Check a sample of files from the album (up to 3 files for efficiency)
    sample_files = album_files[:3]
    
    # Convert RYM metadata to sets for comparison (normalized)
    rym_genres_set = set(genre.lower().strip() for genre in rym_genres)
    rym_groupings_set = set(grouping.lower().strip() for grouping in rym_groupings)
    rym_styles_set = set(style.lower().strip() for style in rym_styles)
    rym_moods_set = set(mood.lower().strip() for mood in rym_moods)
    
    matching_files = 0
    
    for file_path in sample_files:
        try:
            metadata = processor.get_complete_file_metadata(file_path)
            if not metadata:
                continue
            
            # Get existing metadata (normalized)
            existing_genres = set(genre.lower().strip() for genre in metadata.get('genre', []))
            existing_groupings = set(grouping.lower().strip() for grouping in metadata.get('groupings', []))
            existing_styles = set(style.lower().strip() for style in metadata.get('styles', []))
            existing_moods = set(mood.lower().strip() for mood in metadata.get('moods', []))
            
            # Calculate similarity for each metadata type
            genre_similarity = _calculate_similarity(existing_genres, rym_genres_set)
            grouping_similarity = _calculate_similarity(existing_groupings, rym_groupings_set)
            style_similarity = _calculate_similarity(existing_styles, rym_styles_set)
            mood_similarity = _calculate_similarity(existing_moods, rym_moods_set)
            
            # Check if this file matches RYM metadata with tolerance
            # We require high similarity for genres (the most important) and reasonable similarity for others
            if (genre_similarity >= tolerance and 
                grouping_similarity >= max(0.7, tolerance - 0.1) and 
                style_similarity >= max(0.7, tolerance - 0.1) and 
                mood_similarity >= max(0.7, tolerance - 0.1)):
                matching_files += 1
            
        except Exception as e:
            # If we can't read a file, don't count it as matching
            continue
    
    # Consider the album as already having RYM metadata if most sampled files match
    match_ratio = matching_files / len(sample_files) if sample_files else 0
    return match_ratio >= 0.67  # At least 2 out of 3 files should match

def _calculate_similarity(set1: set, set2: set) -> float:
    """Calculate Jaccard similarity between two sets."""
    if not set1 and not set2:
        return 1.0  # Both empty = perfect match
    if not set1 or not set2:
        return 0.0  # One empty, one not = no match
    
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    
    return intersection / union if union > 0 else 0.0

def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Update audio file metadata with RYM genre data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run on music directory
  python rym_file_metadata_updater.py --music-dir /path/to/music
  
  # Actually update files
  python rym_file_metadata_updater.py --music-dir /path/to/music --execute
  
  # Test with first 10 albums only
  python rym_file_metadata_updater.py --music-dir /path/to/music --limit 10
  
  # Smart sampling: test with files from 5 random artists
  python rym_file_metadata_updater.py --music-dir /path/to/music --sample-artists 5
  
  # Combine sampling with album limit for controlled testing
  python rym_file_metadata_updater.py --music-dir /path/to/music --sample-artists 3 --limit 5 --execute
  
  # Force refresh cache before processing
  python rym_file_metadata_updater.py --music-dir /path/to/music --refresh-cache --sample-artists 5
  
  # Force update all albums (skip metadata comparison)
  python rym_file_metadata_updater.py --music-dir /path/to/music --execute --force
  
  # Disable cache (use direct scanning)
  python rym_file_metadata_updater.py --music-dir /path/to/music --no-cache --sample-artists 5
  
  # Non-recursive scan (only top level)
  python rym_file_metadata_updater.py --music-dir /path/to/music --no-recursive

Performance Tips:
  • Use --sample-artists for fast testing on large libraries
  • Use --limit to control number of albums processed
  • Smart sampling is much faster over network/SMB connections
  • Directory cache dramatically speeds up repeated runs
  • Use --refresh-cache if library structure has changed
  • Cache is automatically built on first run and refreshed every 24 hours
  • Folder structure: Artist/Album/Files is assumed for smart sampling
  • Albums with existing RYM metadata are skipped by default (use --force to override)
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
        '--no-recursive', 
        action='store_true', 
        help='Do not scan subdirectories recursively'
    )
    parser.add_argument(
        '--limit', 
        type=int, 
        help='Only process first N albums (for testing)'
    )
    parser.add_argument(
        '--sample-artists', 
        type=int, 
        help='Smart sampling: only scan files from N random artists (much faster for testing)'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable directory caching (use direct scanning)'
    )
    parser.add_argument(
        '--refresh-cache',
        action='store_true',
        help='Force refresh of directory cache before processing'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force update all albums, even if they already have matching RYM metadata'
    )
    
    args = parser.parse_args()
    
    print("🎵 RYM File Metadata Updater")
    print("=" * 50)
    
    # Validation
    if args.sample_artists and args.no_recursive:
        print("❌ --sample-artists requires recursive scanning (remove --no-recursive)")
        return
    
    if args.sample_artists and args.sample_artists < 1:
        print("❌ --sample-artists must be at least 1")
        return
    
    # Update audio files
    update_audio_files(
        music_dir=args.music_dir,
        dry_run=not args.execute,
        recursive=not args.no_recursive,
        limit=args.limit,
        sample_artists=args.sample_artists,
        use_cache=not args.no_cache,
        refresh_cache=args.refresh_cache,
        force_update=args.force
    )

if __name__ == "__main__":
    main() 