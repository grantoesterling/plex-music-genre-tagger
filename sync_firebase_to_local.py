#!/usr/bin/env python3
"""
Firebase to Local RYM Data Sync

Downloads all RYM data from Firebase Realtime Database and saves it locally
for use with genre update scripts and other tools.
"""

import json
import os
import sys
import time
from datetime import datetime
import requests
from typing import Dict, List, Any

# Firebase Realtime Database URL
FIREBASE_URL = "https://rym-soft-scraper-default-rtdb.firebaseio.com/"
LOCAL_CACHE_FILE = "./data/rym-scraped.json"
BACKUP_DIR = "./data/backups"

def ensure_directories():
    """Ensure required directories exist."""
    os.makedirs("./data", exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)

def backup_existing_cache():
    """Backup existing local cache if it exists."""
    if os.path.exists(LOCAL_CACHE_FILE):
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = f"{BACKUP_DIR}/rym-scraped_backup_{timestamp}.json"
            
            # Copy existing file to backup
            with open(LOCAL_CACHE_FILE, 'r', encoding='utf-8') as src:
                with open(backup_file, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
            
            print(f"📁 Backed up existing cache to: {backup_file}")
            return backup_file
            
        except Exception as e:
            print(f"⚠️  Warning: Could not backup existing cache: {e}")
            return None
    
    return None

def test_firebase_connection() -> bool:
    """Test connection to Firebase Realtime Database."""
    try:
        print("🔍 Testing Firebase connection...")
        response = requests.get(f"{FIREBASE_URL}.json?shallow=true", timeout=10)
        
        if response.status_code == 200:
            print("✅ Firebase connection successful")
            return True
        else:
            print(f"❌ Firebase connection failed: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error connecting to Firebase: {e}")
        return False

def get_firebase_stats() -> Dict[str, Any]:
    """Get statistics about data in Firebase."""
    try:
        response = requests.get(f"{FIREBASE_URL}.json?shallow=true", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data and 'releases' in data:
                # Get shallow view of releases to get artist list
                releases_response = requests.get(f"{FIREBASE_URL}releases.json?shallow=true", timeout=30)
                if releases_response.status_code == 200:
                    releases_data = releases_response.json()
                    if releases_data:
                        total_artists = len(releases_data)
                        sample_artists = list(releases_data.keys())[:5]
                        
                        # Sample a few artists to estimate total releases
                        estimated_releases = 0
                        sample_count = 0
                        for artist_slug in sample_artists:
                            try:
                                artist_response = requests.get(f"{FIREBASE_URL}releases/{artist_slug}.json?shallow=true", timeout=10)
                                if artist_response.status_code == 200:
                                    artist_data = artist_response.json()
                                    if isinstance(artist_data, dict):
                                        estimated_releases += len(artist_data)
                                        sample_count += 1
                            except:
                                continue
                        
                        # Estimate total releases based on sample
                        if sample_count > 0:
                            avg_releases_per_artist = estimated_releases / sample_count
                            estimated_total_releases = int(avg_releases_per_artist * total_artists)
                        else:
                            estimated_total_releases = 0
                        
                        return {
                            'total_artists': total_artists,
                            'estimated_releases': estimated_total_releases,
                            'sample_artists': sample_artists,
                            'sample_releases_counted': estimated_releases
                        }
                
                return {'total_artists': 0, 'estimated_releases': 0, 'sample_artists': [], 'sample_releases_counted': 0}
            else:
                return {'total_artists': 0, 'estimated_releases': 0, 'sample_artists': [], 'sample_releases_counted': 0}
        else:
            return {'error': f"HTTP {response.status_code}"}
            
    except Exception as e:
        return {'error': str(e)}

def download_firebase_data() -> List[Dict[str, Any]]:
    """Download all release data from Firebase."""
    try:
        print("📡 Downloading data from Firebase...")
        response = requests.get(f"{FIREBASE_URL}releases.json", timeout=120)
        
        if response.status_code == 200:
            firebase_data = response.json()
            
            if not firebase_data:
                print("⚠️  No data found in Firebase")
                return []
            
            # Convert Firebase nested structure to flat list format
            # Actual structure is: [artist]/[album] directly under releases
            releases_list = []
            total_processed = 0
            
            for artist_slug, albums in firebase_data.items():
                if not isinstance(albums, dict):
                    continue
                    
                artist_count = 0
                artist_name = artist_slug  # Default fallback
                
                for album_slug, album_data in albums.items():
                    if isinstance(album_data, dict):
                        # Convert Firebase format to the expected local format
                        release_entry = {
                            'artistName': album_data.get('artistName', ''),
                            'releaseTitle': album_data.get('releaseTitle', ''),
                            'genres': album_data.get('genres', []),
                            'secondaryGenres': album_data.get('secondaryGenres', []),
                            'descriptors': album_data.get('descriptors', []),
                            'url': album_data.get('url', ''),
                            'scrapedAt': album_data.get('scrapedAt', ''),
                            'uploadedAt': album_data.get('uploadedAt', ''),
                            # Note: release_type not available in this structure
                        }
                        releases_list.append(release_entry)
                        artist_count += 1
                        total_processed += 1
                        
                        # Get artist name from the first valid release data
                        if artist_count == 1 and release_entry.get('artistName'):
                            artist_name = release_entry['artistName']
                    else:
                        print(f"   ⚠️  Skipping invalid album data for {artist_slug}/{album_slug}: expected dict, got {type(album_data)}")
                
                if artist_count > 0:
                    print(f"   🎵 {artist_name}: {artist_count} releases")
            
            print(f"✅ Downloaded {total_processed} releases from Firebase")
            return releases_list
            
        else:
            print(f"❌ Failed to download data: HTTP {response.status_code}")
            if response.text:
                print(f"   Response: {response.text[:200]}...")
            return []
            
    except Exception as e:
        print(f"❌ Error downloading Firebase data: {e}")
        import traceback
        print(f"   Debug info: {traceback.format_exc()}")
        return []

def save_local_cache(releases_data: List[Dict[str, Any]]) -> bool:
    """Save releases data to local cache file."""
    try:
        print(f"💾 Saving {len(releases_data)} releases to local cache...")
        
        # Add metadata to the data
        cache_data = {
            'sync_timestamp': datetime.now().isoformat(),
            'source': 'firebase_sync',
            'firebase_url': FIREBASE_URL,
            'total_releases': len(releases_data),
            'releases': releases_data
        }
        
        # Write to temporary file first
        temp_file = f"{LOCAL_CACHE_FILE}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(releases_data, f, indent=2, ensure_ascii=False)
        
        # Move temp file to final location (atomic operation)
        os.rename(temp_file, LOCAL_CACHE_FILE)
        
        print(f"✅ Successfully saved local cache: {LOCAL_CACHE_FILE}")
        
        # Show file size for reference
        file_size = os.path.getsize(LOCAL_CACHE_FILE)
        print(f"   File size: {file_size / 1024 / 1024:.1f} MB")
        
        return True
        
    except Exception as e:
        print(f"❌ Error saving local cache: {e}")
        return False

def validate_local_cache() -> bool:
    """Validate the saved local cache file."""
    try:
        print("🔍 Validating local cache...")
        
        with open(LOCAL_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            print("❌ Cache validation failed: Expected list format")
            return False
        
        if len(data) == 0:
            print("⚠️  Cache validation warning: No releases found")
            return True
        
        # Check first few entries for expected structure
        sample_entry = data[0]
        required_fields = ['artistName', 'releaseTitle', 'url']
        
        for field in required_fields:
            if field not in sample_entry:
                print(f"❌ Cache validation failed: Missing required field '{field}'")
                return False
        
        print(f"✅ Cache validation successful: {len(data)} releases")
        return True
        
    except Exception as e:
        print(f"❌ Cache validation error: {e}")
        return False

def show_sync_summary(releases_data: List[Dict[str, Any]]):
    """Show summary of the sync operation."""
    if not releases_data:
        return
    
    # Count by artist
    artist_counts = {}
    for release in releases_data:
        artist_name = release.get('artistName', 'Unknown')
        artist_counts[artist_name] = artist_counts.get(artist_name, 0) + 1
    
    print(f"\n📊 Sync Summary:")
    print(f"   Total releases downloaded: {len(releases_data)}")
    print(f"   Total artists: {len(artist_counts)}")
    
    # Show top artists by release count
    top_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    if top_artists:
        print(f"   Top artists by release count:")
        for artist, count in top_artists:
            print(f"     • {artist}: {count} releases")
    
    # Show sample entries
    print(f"\n📝 Sample entries:")
    for i, release in enumerate(releases_data[:3]):
        artist = release.get('artistName', 'Unknown')
        album = release.get('releaseTitle', 'Unknown')
        genres = len(release.get('genres', []))
        print(f"   {i+1}. {artist} - {album} ({genres} genres)")
    
    if len(releases_data) > 3:
        print(f"   ... and {len(releases_data) - 3} more releases")

def main():
    """Main function."""
    print("🔥 Firebase to Local RYM Data Sync")
    print("=" * 50)
    
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Downloads all RYM data from Firebase Realtime Database to local cache.")
        print()
        print("Usage:")
        print("  python sync_firebase_to_local.py [options]")
        print()
        print("Options:")
        print("  --stats-only       Show Firebase database statistics only")
        print("  --no-backup        Skip backing up existing local cache")
        print("  --help, -h         Show this help message")
        print()
        print("Output:")
        print(f"  • Downloads data from: {FIREBASE_URL}")
        print(f"  • Saves to local cache: {LOCAL_CACHE_FILE}")
        print(f"  • Creates backup in: {BACKUP_DIR}")
        print()
        print("The local cache will be compatible with existing RYM processing scripts.")
        return
    
    # Parse command line arguments
    stats_only = "--stats-only" in sys.argv
    no_backup = "--no-backup" in sys.argv
    
    # Ensure directories exist
    ensure_directories()
    
    # Test Firebase connection
    if not test_firebase_connection():
        print("❌ Cannot connect to Firebase. Please check your internet connection.")
        return
    
    # Get and show Firebase stats
    print("\n📊 Firebase Database Statistics:")
    stats = get_firebase_stats()
    if 'error' in stats:
        print(f"   ❌ Error getting stats: {stats['error']}")
        return
    else:
        print(f"   Total artists: {stats['total_artists']}")
        print(f"   Total releases: {stats['estimated_releases']}")
        if stats['sample_artists']:
            print(f"   Sample artists: {', '.join(stats['sample_artists'])}")
    
    if stats_only:
        print("\n✅ Stats-only mode complete!")
        return
    
    if stats['estimated_releases'] == 0:
        print("\n⚠️  No data found in Firebase database")
        return
    
    # Backup existing cache
    if not no_backup:
        print("\n💾 Handling existing cache...")
        backup_existing_cache()
    
    # Download data from Firebase
    print("\n📡 Syncing data from Firebase...")
    releases_data = download_firebase_data()
    
    if not releases_data:
        print("❌ No data downloaded from Firebase")
        return
    
    # Save to local cache
    print("\n💾 Saving local cache...")
    if not save_local_cache(releases_data):
        print("❌ Failed to save local cache")
        return
    
    # Validate the saved cache
    print("\n🔍 Validating cache...")
    if not validate_local_cache():
        print("❌ Cache validation failed")
        return
    
    # Show summary
    show_sync_summary(releases_data)
    
    print(f"\n✅ Sync complete!")
    print(f"📁 Local cache ready: {LOCAL_CACHE_FILE}")
    print(f"💡 You can now use your existing RYM processing scripts with the local cache")

if __name__ == "__main__":
    main() 