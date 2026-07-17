#!/usr/bin/env python3
"""
Find Missing Firebase Releases

Cross-references Firebase database data with Plex cache to identify
which Plex releases are not yet in the Firebase database.

This script:
1. Loads Firebase data from local cache (data/rym-scraped.json)
2. Loads Plex cache data (plex_metadata_cache.json)
3. Performs fuzzy matching to identify missing releases
4. Generates report of Plex releases not found in Firebase

Usage:
    python find_missing_firebase_releases.py [options]
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Any, Set, Tuple
from difflib import SequenceMatcher
import re

# File paths
FIREBASE_CACHE_FILE = "./data/rym-scraped.json"
PLEX_CACHE_FILE = "./plex_metadata_cache.json"
OUTPUT_FILE = f"missing_firebase_releases_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def load_firebase_data() -> List[Dict[str, Any]]:
    """Load Firebase data from local cache."""
    try:
        print("📁 Loading Firebase data from local cache...")
        
        if not os.path.exists(FIREBASE_CACHE_FILE):
            print(f"❌ Firebase cache file not found: {FIREBASE_CACHE_FILE}")
            print("   Run 'python sync_firebase_to_local.py' first to sync Firebase data")
            return []
        
        with open(FIREBASE_CACHE_FILE, 'r', encoding='utf-8') as f:
            firebase_data = json.load(f)
        
        if not isinstance(firebase_data, list):
            print(f"❌ Unexpected Firebase data format: expected list, got {type(firebase_data)}")
            return []
        
        print(f"✅ Loaded {len(firebase_data)} releases from Firebase cache")
        return firebase_data
        
    except Exception as e:
        print(f"❌ Error loading Firebase data: {e}")
        return []

def load_plex_data() -> List[Dict[str, Any]]:
    """Load Plex data from cache."""
    try:
        print("📁 Loading Plex data from cache...")
        
        if not os.path.exists(PLEX_CACHE_FILE):
            print(f"❌ Plex cache file not found: {PLEX_CACHE_FILE}")
            print("   Run 'python refresh_plex_cache.py' first to refresh Plex cache")
            return []
        
        with open(PLEX_CACHE_FILE, 'r', encoding='utf-8') as f:
            plex_cache = json.load(f)
        
        albums = plex_cache.get('albums', [])
        print(f"✅ Loaded {len(albums)} albums from Plex cache")
        
        # Show cache timestamp for reference
        timestamp = plex_cache.get('timestamp', 'Unknown')
        if timestamp != 'Unknown':
            try:
                cache_time = datetime.fromisoformat(timestamp)
                age_hours = (datetime.now() - cache_time).total_seconds() / 3600
                print(f"   Cache age: {age_hours:.1f} hours")
            except:
                print(f"   Cache timestamp: {timestamp}")
        
        return albums
        
    except Exception as e:
        print(f"❌ Error loading Plex data: {e}")
        return []

def normalize_string(s: str) -> str:
    """Normalize strings for comparison by keeping only alphanumeric characters and spaces."""
    if not s:
        return ""
    
    # Convert to lowercase
    s = s.lower()
    
    # Remove common prefixes that can cause mismatches
    s = re.sub(r'^(the|a|an)\s+', '', s)
    s = re.sub(r'\s+(the|a|an)$', '', s)
    
    # Keep Unicode letters, numbers, and spaces - remove punctuation but keep all languages
    s = re.sub(r'[^\w\s]', '', s, flags=re.UNICODE)
    
    # Normalize whitespace (multiple spaces become single space)
    s = re.sub(r'\s+', ' ', s).strip()
    
    return s

def calculate_similarity(str1: str, str2: str) -> float:
    """Calculate similarity between two strings."""
    if not str1 or not str2:
        return 0.0
    
    norm1 = normalize_string(str1)
    norm2 = normalize_string(str2)
    
    if norm1 == norm2:
        return 1.0
    
    return SequenceMatcher(None, norm1, norm2).ratio()

def create_firebase_lookup(firebase_data: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Create a lookup dictionary for Firebase releases."""
    lookup = {}
    
    for release in firebase_data:
        artist = release.get('artistName', '')
        album = release.get('releaseTitle', '')
        
        if not artist or not album:
            continue
        
        # Normalize for lookup
        norm_artist = normalize_string(artist)
        norm_album = normalize_string(album)
        
        if norm_artist not in lookup:
            lookup[norm_artist] = set()
        
        lookup[norm_artist].add(norm_album)
    
    return lookup

def find_missing_releases(
    firebase_data: List[Dict[str, Any]], 
    plex_data: List[Dict[str, Any]],
    similarity_threshold: float = 0.85
) -> List[Dict[str, Any]]:
    """Find Plex releases that are missing from Firebase."""
    
    print(f"🔍 Analyzing releases (similarity threshold: {similarity_threshold})...")
    
    # Create Firebase lookup for fast checking
    firebase_lookup = create_firebase_lookup(firebase_data)
    
    # Create additional lookup for album-only matching
    album_only_lookup = {}
    for release in firebase_data:
        album = release.get('releaseTitle', '')
        artist = release.get('artistName', '')
        
        if not album or not artist:
            continue
        
        norm_album = normalize_string(album)
        if norm_album not in album_only_lookup:
            album_only_lookup[norm_album] = []
        
        album_only_lookup[norm_album].append({
            'artist': artist,
            'album': album,
            'normalized_artist': normalize_string(artist)
        })
    
    missing_releases = []
    total_plex = len(plex_data)
    processed = 0
    
    for plex_album in plex_data:
        processed += 1
        
        if processed % 100 == 0:
            print(f"   Progress: {processed}/{total_plex} albums analyzed...")
        
        plex_artist = plex_album.get('artist', '')
        plex_title = plex_album.get('title', '')
        
        if not plex_artist or not plex_title:
            continue
        
        norm_plex_artist = normalize_string(plex_artist)
        norm_plex_title = normalize_string(plex_title)
        
        # Step 1: Quick exact match check
        if norm_plex_artist in firebase_lookup and norm_plex_title in firebase_lookup[norm_plex_artist]:
            continue
        
        # Step 2: Fuzzy matching for artist + album
        best_match_found = False
        best_artist_match = 0.0
        best_album_match = 0.0
        match_type = 'none'
        
        for fb_artist_norm, fb_albums in firebase_lookup.items():
            artist_similarity = calculate_similarity(norm_plex_artist, fb_artist_norm)
            
            if artist_similarity >= similarity_threshold:
                # Artist matches, check albums
                for fb_album_norm in fb_albums:
                    album_similarity = calculate_similarity(norm_plex_title, fb_album_norm)
                    
                    if album_similarity >= similarity_threshold:
                        best_match_found = True
                        match_type = 'fuzzy_both'
                        break
                    
                    # Track best matches for reporting
                    if artist_similarity > best_artist_match:
                        best_artist_match = artist_similarity
                    if album_similarity > best_album_match:
                        best_album_match = album_similarity
                
                if best_match_found:
                    break
        
        # Step 3: Album-only matching as fallback (like rym_plex_updater)
        if not best_match_found:
            # Skip album-only matching for very common album titles that are likely false matches
            # Use word boundaries to avoid false positives (e.g., "live at venue" vs just "live")
            common_patterns = [
                r'\blive\b(?!\s+at\b)',  # "live" but not "live at [venue]"
                r'\bgreatest hits\b', r'\bbest of\b', r'\bcompilation\b', r'\banthology\b',
                r'\bcollection\b', r'\bsingles\b', r'\bhits\b', r'\bdeluxe\b', 
                r'\bremastered\b', r'\bexpanded\b'
            ]
            
            # Check if the album title matches any generic patterns
            skip_album_only = any(re.search(pattern, norm_plex_title, re.IGNORECASE) for pattern in common_patterns)
            
            if not skip_album_only and norm_plex_title in album_only_lookup:
                # Found potential album-only matches
                fb_matches = album_only_lookup[norm_plex_title]
                
                if len(fb_matches) == 1:
                    # Single match - likely good
                    fb_match = fb_matches[0]
                    artist_similarity = calculate_similarity(norm_plex_artist, fb_match['normalized_artist'])
                    best_match_found = True
                    match_type = 'album_only_single'
                    best_artist_match = artist_similarity
                    best_album_match = 1.0  # Exact album match
                    
                elif len(fb_matches) <= 5:  # Multiple matches but not too many
                    # Check if any artist has reasonable similarity
                    best_fb_match = None
                    best_artist_sim = 0.0
                    
                    for fb_match in fb_matches:
                        artist_sim = calculate_similarity(norm_plex_artist, fb_match['normalized_artist'])
                        if artist_sim > best_artist_sim:
                            best_artist_sim = artist_sim
                            best_fb_match = fb_match
                    
                    # Use a lower threshold for album-only matching (artist names can vary significantly)
                    if best_artist_sim >= 0.3:  # Much lower threshold
                        best_match_found = True
                        match_type = 'album_only_multi'
                        best_artist_match = best_artist_sim
                        best_album_match = 1.0  # Exact album match
                
                # If we found an album-only match, also check for fuzzy album matching
                elif not best_match_found:
                    # Try fuzzy album matching across all Firebase albums
                    for norm_album, fb_matches_list in album_only_lookup.items():
                        album_similarity = calculate_similarity(norm_plex_title, norm_album)
                        
                        if album_similarity >= similarity_threshold:
                            # Found fuzzy album match, check if any artist is reasonable
                            for fb_match in fb_matches_list:
                                artist_similarity = calculate_similarity(norm_plex_artist, fb_match['normalized_artist'])
                                
                                if artist_similarity > best_artist_match:
                                    best_artist_match = artist_similarity
                                if album_similarity > best_album_match:
                                    best_album_match = album_similarity
                                
                                # If combined similarity is good enough, consider it a match
                                combined_similarity = (artist_similarity + album_similarity) / 2
                                if combined_similarity >= similarity_threshold * 0.9:  # Slightly lower threshold
                                    best_match_found = True
                                    match_type = 'fuzzy_album_only'
                                    break
                            
                            if best_match_found:
                                break
        
        if not best_match_found:
            missing_release = {
                'plex_artist': plex_artist,
                'plex_title': plex_title,
                'plex_year': plex_album.get('year'),
                'plex_key': plex_album.get('key'),
                'plex_genres': plex_album.get('genres', []),
                'plex_styles': plex_album.get('styles', []),
                'plex_moods': plex_album.get('moods', []),
                'best_artist_similarity': best_artist_match,
                'best_album_similarity': best_album_match,
                'match_type_attempted': match_type,
                'normalized_artist': norm_plex_artist,
                'normalized_title': norm_plex_title
            }
            missing_releases.append(missing_release)
    
    print(f"✅ Analysis complete: {len(missing_releases)} missing releases found")
    return missing_releases

def generate_report(missing_releases: List[Dict[str, Any]], plex_total: int) -> None:
    """Generate and save a detailed report."""
    try:
        print(f"📊 Generating report...")
        
        # Create comprehensive report
        report = {
            'generated_at': datetime.now().isoformat(),
            'summary': {
                'total_plex_albums': plex_total,
                'missing_from_firebase': len(missing_releases),
                'coverage_percentage': ((plex_total - len(missing_releases)) / plex_total * 100) if plex_total > 0 else 0
            },
            'missing_releases': missing_releases
        }
        
        # Save full report
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Full report saved: {OUTPUT_FILE}")
        
        # Print summary to console
        print(f"\n📊 SUMMARY REPORT")
        print(f"=" * 50)
        print(f"Total Plex albums:        {report['summary']['total_plex_albums']:,}")
        print(f"Missing from Firebase:    {report['summary']['missing_from_firebase']:,}")
        print(f"Firebase coverage:        {report['summary']['coverage_percentage']:.1f}%")
        
        if missing_releases:
            print(f"\n🔍 SAMPLE MISSING RELEASES:")
            for i, release in enumerate(missing_releases[:10]):
                print(f"   {i+1:2d}. {release['plex_artist']} - {release['plex_title']}")
                if release['plex_year']:
                    print(f"       Year: {release['plex_year']}")
                if release['best_artist_similarity'] > 0.5 or release['best_album_similarity'] > 0.5:
                    print(f"       Best matches: Artist {release['best_artist_similarity']:.2f}, Album {release['best_album_similarity']:.2f}")
            
            if len(missing_releases) > 10:
                print(f"   ... and {len(missing_releases) - 10} more releases")
        
        # Show breakdown by genre if available
        genre_counts = {}
        for release in missing_releases:
            for genre in release.get('plex_genres', []):
                genre_counts[genre] = genre_counts.get(genre, 0) + 1
        
        if genre_counts:
            print(f"\n🎵 MISSING RELEASES BY GENRE:")
            sorted_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
            for genre, count in sorted_genres[:10]:
                print(f"   {genre}: {count} releases")
        
        print(f"\n💡 Next steps:")
        print(f"   • Review the full report: {OUTPUT_FILE}")
        print(f"   • Consider scraping missing releases with RYM tools")
        print(f"   • Update Firebase database with new data")
        
    except Exception as e:
        print(f"❌ Error generating report: {e}")

def show_cache_info():
    """Show information about both cache files."""
    print(f"📁 CACHE FILES INFO:")
    print(f"=" * 50)
    
    # Firebase cache info
    if os.path.exists(FIREBASE_CACHE_FILE):
        fb_size = os.path.getsize(FIREBASE_CACHE_FILE) / (1024 * 1024)
        fb_modified = datetime.fromtimestamp(os.path.getmtime(FIREBASE_CACHE_FILE))
        fb_age = (datetime.now() - fb_modified).total_seconds() / 3600
        print(f"Firebase cache: {FIREBASE_CACHE_FILE}")
        print(f"   Size: {fb_size:.1f} MB")
        print(f"   Modified: {fb_modified.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Age: {fb_age:.1f} hours")
    else:
        print(f"Firebase cache: ❌ Not found ({FIREBASE_CACHE_FILE})")
    
    # Plex cache info
    if os.path.exists(PLEX_CACHE_FILE):
        plex_size = os.path.getsize(PLEX_CACHE_FILE) / (1024 * 1024)
        plex_modified = datetime.fromtimestamp(os.path.getmtime(PLEX_CACHE_FILE))
        plex_age = (datetime.now() - plex_modified).total_seconds() / 3600
        print(f"Plex cache: {PLEX_CACHE_FILE}")
        print(f"   Size: {plex_size:.1f} MB")
        print(f"   Modified: {plex_modified.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Age: {plex_age:.1f} hours")
    else:
        print(f"Plex cache: ❌ Not found ({PLEX_CACHE_FILE})")

def main():
    """Main function."""
    print("🔍 Find Missing Firebase Releases")
    print("=" * 50)
    
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Cross-references Firebase database data with Plex cache to identify")
        print("which Plex releases are not yet in the Firebase database.")
        print()
        print("Usage:")
        print("  python find_missing_firebase_releases.py [options]")
        print()
        print("Options:")
        print("  --threshold N      Set similarity threshold (0.1-1.0, default: 0.85)")
        print("  --cache-info       Show cache file information only")
        print("  --help, -h         Show this help message")
        print()
        print("Prerequisites:")
        print("  • Firebase cache: Run 'python sync_firebase_to_local.py' first")
        print("  • Plex cache: Run 'python refresh_plex_cache.py' first")
        print()
        print("Output:")
        print(f"  • Detailed JSON report: missing_firebase_releases_TIMESTAMP.json")
        print("  • Console summary with statistics")
        return
    
    # Parse command line arguments
    similarity_threshold = 0.85
    cache_info_only = "--cache-info" in sys.argv
    
    for arg in sys.argv[1:]:
        if arg.startswith("--threshold"):
            try:
                if "=" in arg:
                    threshold_str = arg.split("=")[1]
                else:
                    # Get next argument
                    idx = sys.argv.index(arg)
                    if idx + 1 < len(sys.argv):
                        threshold_str = sys.argv[idx + 1]
                    else:
                        raise ValueError("No threshold value provided")
                
                similarity_threshold = float(threshold_str)
                if not 0.1 <= similarity_threshold <= 1.0:
                    raise ValueError("Threshold must be between 0.1 and 1.0")
                print(f"🎯 Using similarity threshold: {similarity_threshold}")
            except (ValueError, IndexError) as e:
                print(f"❌ Invalid threshold value: {e}")
                return
    
    # Show cache info
    show_cache_info()
    
    if cache_info_only:
        return
    
    print()
    
    # Load data
    firebase_data = load_firebase_data()
    if not firebase_data:
        return
    
    plex_data = load_plex_data()
    if not plex_data:
        return
    
    # Find missing releases
    missing_releases = find_missing_releases(firebase_data, plex_data, similarity_threshold)
    
    # Generate report
    generate_report(missing_releases, len(plex_data))

if __name__ == "__main__":
    main() 