#!/usr/bin/env python3
"""
RYM Firebase Uploader

Uploads all entries from rym-scraped.json to Firebase Realtime Database.
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
RYM_SCRAPED_FILE = "./data/missing_releases.json"

def load_rym_scraped_data() -> List[Dict[str, Any]]:
    """Load RYM scraped data from JSON file."""
    if not os.path.exists(RYM_SCRAPED_FILE):
        print(f"❌ RYM scraped file not found: {RYM_SCRAPED_FILE}")
        return []
    
    try:
        with open(RYM_SCRAPED_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"📊 Loaded {len(data)} albums from RYM scraped data")
        return data
        
    except Exception as e:
        print(f"❌ Error loading RYM scraped data: {e}")
        return []

def create_album_key(artist_name: str, release_title: str) -> str:
    """Create a unique key for a release based on artist name and release title.
    
    Constructs a Firebase-safe key like: 'releases/artist-name/release-title'
    """
    if not artist_name or not release_title:
        return None
    
    try:
        # Convert to lowercase and replace spaces with dashes
        clean_artist = artist_name.lower().strip()
        clean_title = release_title.lower().strip()
        
        # Replace problematic characters for Firebase keys
        def clean_for_firebase(text):
            # Replace spaces with dashes
            text = text.replace(' ', '-')
            # Replace other problematic characters
            replacements = {
                '.': '-', '#': '-', '$': '-', '[': '-', ']': '-', 
                '/': '-', '\\': '-', '&': 'and', '+': 'plus',
                '?': '', '!': '', '*': '', '(': '', ')': '',
                ',': '', ':': '', ';': '', '"': '', "'": '',
                '=': '', '%': '', '@': '', '<': '', '>': ''
            }
            for old, new in replacements.items():
                text = text.replace(old, new)
            
            # Remove multiple consecutive dashes and strip dashes from ends
            while '--' in text:
                text = text.replace('--', '-')
            text = text.strip('-')
            
            return text
        
        clean_artist = clean_for_firebase(clean_artist)
        clean_title = clean_for_firebase(clean_title)
        
        # Construct the key with releases prefix
        key = f"releases/{clean_artist}/{clean_title}"
        return key
        
    except Exception as e:
        print(f"   ⚠️  Error creating key for {artist_name} - {release_title}: {e}")
        return None

def upload_to_firebase(data: List[Dict[str, Any]], batch_size: int = 100) -> bool:
    """Upload data to Firebase Realtime Database in batches."""
    if not data:
        print("❌ No data to upload")
        return False
    
    total_albums = len(data)
    uploaded_count = 0
    error_count = 0
    
    print(f"🚀 Starting upload of {total_albums} albums to Firebase...")
    print(f"   Database URL: {FIREBASE_URL}")
    print(f"   Batch size: {batch_size}")
    
    # Process in batches
    for i in range(0, total_albums, batch_size):
        batch = data[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_albums + batch_size - 1) // batch_size
        
        print(f"\n📦 Processing batch {batch_num}/{total_batches} ({len(batch)} albums)...")
        
        # Prepare batch data for Firebase
        batch_updates = {}
        
        for album in batch:
            try:
                artist_name = album.get('artistName', '')
                album_title = album.get('releaseTitle', '')
                rym_url = album.get('url', '')
                
                if not artist_name or not album_title:
                    print(f"   ⚠️  Skipping album with missing artist or title: {album}")
                    continue
                
                # Create unique key for this album from artist name and title
                album_key = create_album_key(artist_name, album_title)
                
                if not album_key:
                    print(f"   ⚠️  Skipping album with invalid key generation: {artist_name} - {album_title}")
                    continue
                
                # Prepare album data for Firebase
                firebase_album = {
                    'artistName': artist_name,
                    'releaseTitle': album_title,
                    'genres': album.get('genres', []),
                    'secondaryGenres': album.get('secondaryGenres', []),
                    'descriptors': album.get('descriptors', []),
                    # 'url': rym_url,
                    'scrapedAt': album.get('scrapedAt', ''),
                    'uploadedAt': datetime.now().isoformat()
                }
                
                # Add to batch updates (note: no 'albums/' prefix since key already contains path)
                batch_updates[album_key] = firebase_album
                
            except Exception as e:
                print(f"   ❌ Error preparing album {album.get('artistName', '')} - {album.get('albumTitle', '')}: {e}")
                error_count += 1
                continue
        
        if not batch_updates:
            print(f"   ⚠️  No valid albums in batch {batch_num}")
            continue
        
        # Upload batch to Firebase
        try:
            response = requests.patch(
                f"{FIREBASE_URL}.json",
                json=batch_updates,
                timeout=30
            )
            
            if response.status_code == 200:
                uploaded_count += len(batch_updates)
                print(f"   ✅ Successfully uploaded {len(batch_updates)} albums")
            else:

                print(f"   ❌ Firebase error: {response.status_code} - {response.text}")
                error_count += len(batch_updates)
                
        except Exception as e:
            print(f"   ❌ Error uploading batch {batch_num}: {e}")
            error_count += len(batch_updates)
        
        # Small delay between batches to be nice to Firebase
        if i + batch_size < total_albums:
            time.sleep(1)
    
    # Summary
    print(f"\n📈 Upload Summary:")
    print(f"   Total albums processed: {total_albums}")
    print(f"   Successfully uploaded: {uploaded_count}")
    if error_count > 0:
        print(f"   Errors: {error_count}")
    
    success_rate = (uploaded_count / total_albums) * 100 if total_albums > 0 else 0
    print(f"   Success rate: {success_rate:.1f}%")
    
    return uploaded_count > 0

def check_firebase_connection() -> bool:
    """Test connection to Firebase Realtime Database."""
    try:
        print("🔍 Testing Firebase connection...")
        response = requests.get(f"{FIREBASE_URL}.json?shallow=true", timeout=10)
        
        if response.status_code == 200:
            print("✅ Firebase connection successful")
            return True
        else:
            print(f"❌ Firebase connection failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error connecting to Firebase: {e}")
        return False

def get_firebase_stats() -> Dict[str, Any]:
    """Get statistics about existing data in Firebase."""
    try:
        response = requests.get(f"{FIREBASE_URL}releases.json?shallow=true", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data:
                all_keys = list(data.keys())
                return {
                    'existing_releases': len(all_keys),
                    'sample_keys': [f"releases/{key}" for key in all_keys[:5]]
                }
            else:
                return {'existing_releases': 0, 'sample_keys': []}
        else:
            return {'error': f"HTTP {response.status_code}"}
            
    except Exception as e:
        return {'error': str(e)}

def main():
    """Main function."""
    print("🔥 RYM Firebase Uploader")
    print("=" * 50)
    
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Uploads RYM scraped data to Firebase Realtime Database.")
        print()
        print("Usage:")
        print("  python upload_to_firebase.py [options]")
        print()
        print("Options:")
        print("  --execute          Actually upload data (default is dry run)")
        print("  --batch-size N     Upload in batches of N albums (default: 100)")
        print("  --limit N          Only process first N albums (for testing)")
        print("  --stats            Show existing Firebase database statistics")
        print("  --test-connection  Test Firebase connection only")
        print("  --help, -h         Show this help message")
        print()
        print("Examples:")
        print("  # Test connection")
        print("  python upload_to_firebase.py --test-connection")
        print()
        print("  # Dry run (show what would be uploaded)")
        print("  python upload_to_firebase.py")
        print()
        print("  # Actually upload data")
        print("  python upload_to_firebase.py --execute")
        print()
        print("  # Upload with smaller batches")
        print("  python upload_to_firebase.py --execute --batch-size 50")
        print()
        print("  # Check existing database stats")
        print("  python upload_to_firebase.py --stats")
        return
    
    # Parse command line arguments
    execute = "--execute" in sys.argv
    test_connection = "--test-connection" in sys.argv
    show_stats = "--stats" in sys.argv
    
    batch_size = 100  # default
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
    
    # Test connection if requested
    if test_connection:
        check_firebase_connection()
        return
    
    # Show stats if requested
    if show_stats:
        if not check_firebase_connection():
            return
        
        print("\n📊 Firebase Database Statistics:")
        stats = get_firebase_stats()
        if 'error' in stats:
            print(f"   ❌ Error getting stats: {stats['error']}")
        else:
            print(f"   Existing releases: {stats['existing_releases']}")
            if stats['sample_keys']:
                print(f"   Sample keys: {stats['sample_keys']}")
        return
    
    # Check Firebase connection
    if not check_firebase_connection():
        print("❌ Cannot connect to Firebase. Please check the database URL and your internet connection.")
        return
    
    # Load RYM data
    print("\n📊 Loading RYM scraped data...")
    rym_data = load_rym_scraped_data()
    if not rym_data:
        return
    
    # Apply limit if specified for testing
    if limit:
        original_count = len(rym_data)
        rym_data = rym_data[:limit]
        print(f"🧪 Testing mode: Processing first {len(rym_data)} of {original_count} albums (--limit {limit})")
    
    # Show existing Firebase stats
    print("\n📊 Checking existing Firebase data...")
    stats = get_firebase_stats()
    if 'error' not in stats:
        print(f"   Current releases in Firebase: {stats['existing_releases']}")
    
    if not execute:
        print("\n🔍 DRY RUN MODE - No data will be uploaded")
        print("   Use --execute to actually upload data")
        print(f"   Would upload {len(rym_data)} albums in batches of {batch_size}")
        
        # Show sample of what would be uploaded
        print("\n📝 Sample albums that would be uploaded:")
        for i, album in enumerate(rym_data[:5]):
            artist = album.get('artistName', 'Unknown')
            title = album.get('releaseTitle', 'Unknown')
            genres = len(album.get('genres', []))
            descriptors = len(album.get('descriptors', []))
            print(f"   {i+1}. {artist} - {title} ({genres} genres, {descriptors} descriptors)")
        
        if len(rym_data) > 5:
            print(f"   ... and {len(rym_data) - 5} more albums")
        
        return
    
    # Upload data
    print(f"\n🚀 Uploading {len(rym_data)} albums to Firebase...")
    success = upload_to_firebase(rym_data, batch_size)
    
    if success:
        print("\n✅ Upload completed successfully!")
        print("💡 You can view your data at:")
        print(f"   {FIREBASE_URL}.json")
        print("💡 Releases are stored with keys like 'releases/artist-name/release-title'")
    else:
        print("\n❌ Upload failed!")

if __name__ == "__main__":
    main() 