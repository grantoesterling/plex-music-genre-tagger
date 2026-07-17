#!/usr/bin/env python3
"""
Music Directory Cache

Caches music directory structure to avoid slow SMB scanning on repeated runs.
Stores artist directories, albums, and file paths for fast access.
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class MusicDirectoryCache:
    """Handles caching of music directory structure."""
    
    def __init__(self, cache_file: str = "music_directory_cache.json"):
        self.cache_file = cache_file
        self.cache_data = None
        
    def is_cache_valid(self, music_dir: Path, max_age_hours: int = 24) -> bool:
        """Check if cache exists and is not too old."""
        if not os.path.exists(self.cache_file):
            return False
            
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_info = json.load(f)
            
            # Check if it's for the same directory
            if cache_info.get('music_directory') != str(music_dir):
                return False
            
            # Check age
            cache_time = datetime.fromisoformat(cache_info.get('timestamp', ''))
            age = datetime.now() - cache_time
            
            if age > timedelta(hours=max_age_hours):
                return False
                
            print(f"✅ Found valid cache from {cache_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Cache age: {age.total_seconds()/3600:.1f} hours")
            return True
            
        except Exception as e:
            print(f"⚠️  Error checking cache validity: {e}")
            return False
    
    def load_cache(self) -> Optional[Dict]:
        """Load cache data from file."""
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                self.cache_data = json.load(f)
            
            artists_count = len(self.cache_data.get('artists', {}))
            total_files = sum(len(files) for artist_data in self.cache_data.get('artists', {}).values() 
                            for files in artist_data.get('albums', {}).values())
            
            print(f"📁 Loaded cache: {artists_count} artists, {total_files} files")
            return self.cache_data
            
        except Exception as e:
            print(f"❌ Error loading cache: {e}")
            return None
    
    def build_cache(self, music_dir: Path, supported_extensions: set) -> Dict:
        """Build cache by scanning music directory."""
        print(f"🔄 Building directory cache for: {music_dir}")
        print("   This may take a while over SMB, but will speed up future runs...")
        
        # Import here to avoid circular imports
        import sys
        import os
        sys.path.append(os.path.dirname(__file__))
        
        try:
            import mutagen
        except ImportError:
            print("❌ Error: mutagen library required for metadata caching")
            return {}
        
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'music_directory': str(music_dir),
            'artists': {},
            'files_metadata': {}  # New: store file metadata
        }
        
        # Get artist directories
        artist_dirs = []
        try:
            for item in music_dir.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    artist_dirs.append(item)
        except Exception as e:
            print(f"❌ Error reading music directory: {e}")
            return cache_data
        
        print(f"   Found {len(artist_dirs)} artist directories")
        
        # Quick count of total files to give user an estimate
        print("   Counting total files for progress estimation...")
        estimated_total_files = 0
        for artist_dir in artist_dirs[:min(10, len(artist_dirs))]:  # Sample first 10 artists
            try:
                for filepath in artist_dir.rglob("*"):
                    if filepath.is_file() and filepath.suffix.lower() in supported_extensions:
                        estimated_total_files += 1
            except:
                continue
        
        # Extrapolate from sample
        if len(artist_dirs) > 10:
            avg_files_per_artist = estimated_total_files / min(10, len(artist_dirs))
            estimated_total_files = int(avg_files_per_artist * len(artist_dirs))
            print(f"   Estimated {estimated_total_files:,} total audio files to process")
        else:
            print(f"   Found {estimated_total_files:,} total audio files to process")
        
        print("   Extracting metadata for fast grouping...")
        
        # Scan each artist
        artists_processed = 0
        total_files = 0
        files_with_metadata = 0
        files_processed = 0
        start_time = time.time()
        
        for artist_dir in artist_dirs:
            artists_processed += 1
            artist_files_processed = 0
            
            # Show artist progress every 10 artists instead of 50
            if artists_processed % 10 == 0:
                elapsed_time = time.time() - start_time
                if artists_processed > 0:
                    avg_time_per_artist = elapsed_time / artists_processed
                    remaining_artists = len(artist_dirs) - artists_processed
                    eta_seconds = avg_time_per_artist * remaining_artists
                    eta_minutes = eta_seconds / 60
                    
                    print(f"   Progress: {artists_processed}/{len(artist_dirs)} artists ({artists_processed/len(artist_dirs)*100:.1f}%), {files_with_metadata} files with metadata, ETA: {eta_minutes:.1f} min")
                else:
                    print(f"   Progress: {artists_processed}/{len(artist_dirs)} artists ({artists_processed/len(artist_dirs)*100:.1f}%), {files_with_metadata} files with metadata...")
            
            try:
                artist_data = {
                    'name': artist_dir.name,
                    'path': str(artist_dir),
                    'albums': {}
                }
                
                # Find all audio files for this artist and extract metadata
                audio_files = []
                for filepath in artist_dir.rglob("*"):
                    if filepath.is_file() and filepath.suffix.lower() in supported_extensions:
                        audio_files.append(filepath)
                        files_processed += 1
                        artist_files_processed += 1
                        
                        # Show file progress every 50 files for very large libraries (reduced from 100)
                        if files_processed % 50 == 0:
                            progress_percent = (files_processed / estimated_total_files * 100) if estimated_total_files > 0 else 0
                            print(f"      File progress: {files_processed:,}/{estimated_total_files:,} files ({progress_percent:.1f}%), current artist: {artist_dir.name}")
                        
                        # Extract basic metadata
                        try:
                            audiofile = mutagen.File(filepath)
                            if audiofile is not None:
                                metadata = self._extract_basic_metadata(audiofile, filepath)
                                cache_data['files_metadata'][str(filepath)] = metadata
                                files_with_metadata += 1
                        except Exception as e:
                            # Store minimal metadata if extraction fails
                            cache_data['files_metadata'][str(filepath)] = {
                                'artist': None,
                                'album': None,
                                'title': None,
                                'format': filepath.suffix.lower()[1:]
                            }
                
                # Group files by album (parent directory name as fallback)
                albums = {}
                for filepath in audio_files:
                    album_dir = filepath.parent
                    album_name = album_dir.name
                    
                    if album_name not in albums:
                        albums[album_name] = []
                    albums[album_name].append(str(filepath))
                
                artist_data['albums'] = albums
                artist_data['total_files'] = len(audio_files)
                total_files += len(audio_files)
                
                cache_data['artists'][artist_dir.name] = artist_data
                
            except Exception as e:
                print(f"   ⚠️  Error scanning {artist_dir.name}: {e}")
                continue
        
        cache_data['total_artists'] = len(cache_data['artists'])
        cache_data['total_files'] = total_files
        cache_data['files_with_metadata'] = files_with_metadata
        
        print(f"   ✅ Cache built: {len(cache_data['artists'])} artists, {total_files} files, {files_with_metadata} with metadata")
        
        # Save cache
        self.save_cache(cache_data)
        self.cache_data = cache_data
        
        return cache_data
    
    def _extract_basic_metadata(self, audiofile, filepath: Path) -> dict:
        """Extract basic metadata from audio file."""
        try:
            from mutagen.flac import FLAC
            from mutagen.mp3 import MP3
            from mutagen.mp4 import MP4
            from mutagen.oggvorbis import OggVorbis
            
            metadata = {
                'artist': None,
                'album': None,
                'title': None,
                'format': filepath.suffix.lower()[1:]
            }
            
            if isinstance(audiofile, FLAC):
                metadata['artist'] = self._get_flac_tag(audiofile, 'ARTIST')
                metadata['album'] = self._get_flac_tag(audiofile, 'ALBUM')
                metadata['title'] = self._get_flac_tag(audiofile, 'TITLE')
            elif isinstance(audiofile, MP3):
                if audiofile.tags:
                    metadata['artist'] = self._get_mp3_tag(audiofile, 'TPE1')
                    metadata['album'] = self._get_mp3_tag(audiofile, 'TALB')
                    metadata['title'] = self._get_mp3_tag(audiofile, 'TIT2')
            elif isinstance(audiofile, MP4):
                metadata['artist'] = self._get_mp4_tag(audiofile, '\xa9ART')
                metadata['album'] = self._get_mp4_tag(audiofile, '\xa9alb')
                metadata['title'] = self._get_mp4_tag(audiofile, '\xa9nam')
            elif isinstance(audiofile, OggVorbis):
                metadata['artist'] = self._get_flac_tag(audiofile, 'ARTIST')
                metadata['album'] = self._get_flac_tag(audiofile, 'ALBUM')
                metadata['title'] = self._get_flac_tag(audiofile, 'TITLE')
            
            return metadata
            
        except Exception:
            return {
                'artist': None,
                'album': None,
                'title': None,
                'format': filepath.suffix.lower()[1:]
            }
    
    def _get_flac_tag(self, audiofile, tag_name: str) -> str:
        """Get tag value from FLAC/OGG file."""
        if tag_name in audiofile:
            value = audiofile[tag_name]
            if isinstance(value, list) and value:
                return str(value[0])
            return str(value) if value else None
        return None
    
    def _get_mp3_tag(self, audiofile, tag_name: str) -> str:
        """Get tag value from MP3 file."""
        if tag_name in audiofile.tags:
            value = audiofile.tags[tag_name].text
            if isinstance(value, list) and value:
                return str(value[0])
            return str(value) if value else None
        return None
    
    def _get_mp4_tag(self, audiofile, tag_name: str) -> str:
        """Get tag value from MP4 file."""
        if tag_name in audiofile:
            value = audiofile[tag_name]
            if isinstance(value, list) and value:
                return str(value[0])
            return str(value) if value else None
        return None
    
    def save_cache(self, cache_data: Dict):
        """Save cache data to file."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            print(f"💾 Cache saved to: {self.cache_file}")
            
        except Exception as e:
            print(f"❌ Error saving cache: {e}")
    
    def get_artist_directories(self) -> List[Path]:
        """Get list of artist directory paths from cache."""
        if not self.cache_data:
            return []
        
        return [Path(artist_data['path']) for artist_data in self.cache_data['artists'].values()]
    
    def get_random_artists(self, count: int) -> List[Path]:
        """Get random artist directories from cache."""
        import random
        
        artist_dirs = self.get_artist_directories()
        return random.sample(artist_dirs, min(count, len(artist_dirs)))
    
    def get_files_for_artists(self, artist_names: List[str]) -> List[Path]:
        """Get all files for specified artists from cache."""
        files = []
        
        if not self.cache_data:
            return files
        
        for artist_name in artist_names:
            if artist_name in self.cache_data['artists']:
                artist_data = self.cache_data['artists'][artist_name]
                for album_files in artist_data['albums'].values():
                    files.extend([Path(f) for f in album_files])
        
        return files
    
    def get_all_files(self) -> List[Path]:
        """Get all audio files from cache."""
        files = []
        
        if not self.cache_data:
            return files
        
        for artist_data in self.cache_data['artists'].values():
            for album_files in artist_data['albums'].values():
                files.extend([Path(f) for f in album_files])
        
        return files
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        if not self.cache_data:
            return {}
        
        return {
            'timestamp': self.cache_data.get('timestamp'),
            'music_directory': self.cache_data.get('music_directory'),
            'total_artists': self.cache_data.get('total_artists', 0),
            'total_files': self.cache_data.get('total_files', 0),
            'files_with_metadata': self.cache_data.get('files_with_metadata', 0)
        }
    
    def get_file_metadata(self, filepath: Path) -> dict:
        """Get cached metadata for a file."""
        if not self.cache_data or 'files_metadata' not in self.cache_data:
            return None
        
        return self.cache_data['files_metadata'].get(str(filepath))
    
    def get_albums_from_cache(self) -> dict:
        """Group files by album using cached metadata (much faster than reading files)."""
        if not self.cache_data or 'files_metadata' not in self.cache_data:
            return {}
        
        albums = {}
        files_processed = 0
        files_with_artist_album = 0
        
        print("📋 Grouping files by album using cached metadata...")
        
        for filepath_str, metadata in self.cache_data['files_metadata'].items():
            files_processed += 1
            
            # Show progress every 1000 files (much faster now)
            if files_processed % 1000 == 0:
                print(f"   Progress: Processed {files_processed}/{len(self.cache_data['files_metadata'])} files, found {len(albums)} albums...")
            
            artist = metadata.get('artist')
            album = metadata.get('album')
            
            if artist and album:
                files_with_artist_album += 1
                album_key = f"{artist}|||{album}".lower()
                
                if album_key not in albums:
                    albums[album_key] = {
                        'artist': artist,
                        'album': album,
                        'files': []
                    }
                
                albums[album_key]['files'].append(Path(filepath_str))
        
        print(f"📊 Grouped {files_with_artist_album} files into {len(albums)} albums (using cached metadata)")
        print(f"   Files without artist/album metadata: {files_processed - files_with_artist_album}")
        
        return albums
    
    def refresh_cache(self, music_dir: Path, supported_extensions: set, force: bool = False):
        """Refresh cache if needed or forced."""
        if force or not self.is_cache_valid(music_dir):
            print("🔄 Refreshing music directory cache...")
            self.build_cache(music_dir, supported_extensions)
        else:
            self.load_cache()

def main():
    """Test the cache system."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage music directory cache")
    parser.add_argument('--music-dir', required=True, help='Path to music directory')
    parser.add_argument('--refresh', action='store_true', help='Force refresh cache')
    parser.add_argument('--stats', action='store_true', help='Show cache statistics')
    
    args = parser.parse_args()
    
    print("🎵 Music Directory Cache Manager")
    print("=" * 50)
    
    cache = MusicDirectoryCache()
    music_path = Path(args.music_dir)
    
    if args.refresh:
        # Force refresh
        supported_extensions = {'.flac', '.mp3', '.m4a', '.ogg', '.opus'}
        cache.build_cache(music_path, supported_extensions)
    
    elif args.stats:
        # Show stats
        if cache.is_cache_valid(music_path):
            cache.load_cache()
            stats = cache.get_cache_stats()
            print(f"\n📊 Cache Statistics:")
            print(f"   Directory: {stats.get('music_directory')}")
            print(f"   Last updated: {stats.get('timestamp')}")
            print(f"   Artists: {stats.get('total_artists')}")
            print(f"   Files: {stats.get('total_files')}")
            print(f"   Files with metadata: {stats.get('files_with_metadata', 'N/A')}")
            
            # Show percentage if both values are available
            total_files = stats.get('total_files', 0)
            files_with_metadata = stats.get('files_with_metadata', 0)
            if total_files > 0 and files_with_metadata is not None:
                percentage = (files_with_metadata / total_files) * 100
                print(f"   Metadata coverage: {percentage:.1f}%")
        else:
            print("❌ No valid cache found")
    
    else:
        # Check cache status
        if cache.is_cache_valid(music_path):
            print("✅ Cache is valid and up to date")
        else:
            print("❌ Cache is missing or outdated")
            print("   Run with --refresh to build cache")

if __name__ == "__main__":
    main() 