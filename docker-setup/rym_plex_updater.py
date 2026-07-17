#!/usr/bin/env python3
"""
RYM Plex Metadata Updater

Updates Plex music library metadata using RYM data from Firebase with hierarchical genre expansion.
- Primary genres → Genres (with hierarchical expansion)
- Secondary genres → Styles (no expansion)
- Descriptors → Moods (no expansion)
"""

import ssl
import urllib3
import json
import os
import csv
import pandas as pd
import logging
import time
import re
import requests
import unicodedata
from datetime import datetime
from plexapi.server import PlexServer
from difflib import SequenceMatcher
from rym_genre_hierarchy import RYMGenreHierarchy
from typing import Dict, List, Any

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
CACHE_FILE = "plex_metadata_cache.json"
FIREBASE_URL = "https://rym-soft-scraper-default-rtdb.firebaseio.com/"
RYM_DESCRIPTOR_TREE_FILE = "./data/rym-descriptor-tree.json"

def title_case_tag(tag: str) -> str:
    """Convert a tag to proper title case."""
    # Special corrections for common music terms
    special_corrections = {
        'hip-hop': 'Hip Hop',
        'hiphop': 'Hip Hop',
        'alt-country': 'Alt-Country',
        'alt country': 'Alt-Country',
        'r&b': 'R&B',
        'rnb': 'R&B',
    }
    
    # Check for special corrections first (case-insensitive)
    tag_lower = tag.lower().strip()
    if tag_lower in special_corrections:
        return special_corrections[tag_lower]
    
    # Handle compound terms with R&B
    if 'r&b' in tag_lower:
        # Replace r&b with R&B in the original tag, preserving case of other parts
        corrected = re.sub(r'\br&b\b', 'R&B', tag, flags=re.IGNORECASE)
        # Continue processing the rest normally, but skip the r&b part
        if corrected != tag:
            return title_case_tag_without_rb_correction(corrected)
    
    return title_case_tag_without_rb_correction(tag)

def title_case_tag_without_rb_correction(tag: str) -> str:
    """Title case without R&B correction to avoid infinite recursion."""
    # Words to keep lowercase unless they're the first or last word
    lowercase_words = {'a', 'an', 'the', 'and', 'or', 'but', 'for', 'nor', 'on', 'at', 'to', 'from', 'by', 'in', 'of'}
    
    # Words to keep uppercase
    uppercase_words = {'id', 'uk', 'usa', 'us', 'eu', 'ep', 'lp', 'cd', 'dvd', 'bluray', 'hd', '4k', 'uhd', 'r&b'}
    
    # Handle slashes by processing each part separately
    if '/' in tag:
        parts = tag.split('/')
        processed_parts = []
        for part in parts:
            processed_parts.append(title_case_tag(part.strip()))
        return '/'.join(processed_parts)
    
    # Handle dashes by processing each part separately
    if '-' in tag:
        parts = tag.split('-')
        processed_parts = []
        for part in parts:
            processed_parts.append(title_case_tag(part.strip()))
        return '-'.join(processed_parts)
    
    # Split into words
    words = tag.split()
    
    # Process each word
    for i, word in enumerate(words):
        word_lower = word.lower()
        
        # Keep certain words uppercase
        if word_lower in uppercase_words:
            if word_lower == 'r&b':
                words[i] = 'R&B'
            else:
                words[i] = word.upper()
        # Keep certain words lowercase unless they're first or last
        elif word_lower in lowercase_words and i != 0 and i != len(words) - 1:
            words[i] = word_lower
        # Capitalize other words
        else:
            words[i] = word.capitalize()
    
    return ' '.join(words)

def string_similarity(a: str, b: str) -> float:
    """Calculate string similarity ratio between two strings with Unicode normalization."""
    # Normalize Unicode to handle different representations of the same characters
    a_norm = unicodedata.normalize('NFKC', a.lower())
    b_norm = unicodedata.normalize('NFKC', b.lower())
    return SequenceMatcher(None, a_norm, b_norm).ratio()

def get_artist_variations(artist_name: str) -> List[str]:
    """Generate variations of artist name for better matching, with Unicode support."""
    # Start with the original and Unicode-normalized version
    variations = [artist_name]
    
    # Normalize Unicode (handles different representations of same characters)
    normalized = unicodedata.normalize('NFKC', artist_name)
    if normalized != artist_name:
        variations.append(normalized)
    
    # Remove content in brackets/parentheses (e.g., "Artist [Alt Name]" -> "Artist")
    cleaned = re.sub(r'\s*\[.*?\]\s*', '', artist_name).strip()
    if cleaned and cleaned != artist_name:
        variations.append(cleaned)
        # Also add normalized version of cleaned
        cleaned_norm = unicodedata.normalize('NFKC', cleaned)
        if cleaned_norm != cleaned:
            variations.append(cleaned_norm)
    
    cleaned_parens = re.sub(r'\s*\(.*?\)\s*', '', artist_name).strip()
    if cleaned_parens and cleaned_parens != artist_name:
        variations.append(cleaned_parens)
        # Also add normalized version
        parens_norm = unicodedata.normalize('NFKC', cleaned_parens)
        if parens_norm != cleaned_parens:
            variations.append(parens_norm)
    
    # Extract content from brackets as alternate name (common for Japanese artists)
    bracket_match = re.search(r'\[(.*?)\]', artist_name)
    if bracket_match:
        alt_name = bracket_match.group(1).strip()
        if alt_name:
            variations.append(alt_name)
            # Add normalized version
            alt_norm = unicodedata.normalize('NFKC', alt_name)
            if alt_norm != alt_name:
                variations.append(alt_norm)
    
    # Extract content from parentheses as alternate name  
    paren_match = re.search(r'\((.*?)\)', artist_name)
    if paren_match:
        alt_name = paren_match.group(1).strip()
        if alt_name:
            variations.append(alt_name)
            # Add normalized version
            alt_norm = unicodedata.normalize('NFKC', alt_name)
            if alt_norm != alt_name:
                variations.append(alt_norm)
    
    # For text that might contain both Unicode and ASCII, try decomposed forms
    try:
        # NFD normalization (decomposed form) - useful for some Unicode edge cases
        nfd_normalized = unicodedata.normalize('NFD', artist_name)
        if nfd_normalized != artist_name and nfd_normalized != normalized:
            variations.append(nfd_normalized)
    except:
        pass
    
    # Remove empty strings and duplicates while preserving order
    seen = set()
    result = []
    for var in variations:
        var_clean = var.strip()
        if var_clean and var_clean not in seen:
            seen.add(var_clean)
            result.append(var_clean)
    
    return result

def get_album_variations(album_title: str) -> List[str]:
    """Generate variations of album title for better matching, with Unicode support."""
    # Start with the original and Unicode-normalized version
    variations = [album_title]
    
    # Normalize Unicode (handles different representations of same characters)
    normalized = unicodedata.normalize('NFKC', album_title)
    if normalized != album_title:
        variations.append(normalized)
    
    # Remove content in parentheses (e.g., "Title (Extra Info)" -> "Title")
    cleaned_parens = re.sub(r'\s*\([^)]*\)\s*', '', album_title).strip()
    if cleaned_parens and cleaned_parens != album_title:
        variations.append(cleaned_parens)
        # Add normalized version
        parens_norm = unicodedata.normalize('NFKC', cleaned_parens)
        if parens_norm != cleaned_parens:
            variations.append(parens_norm)
    
    # Remove content in brackets (e.g., "Title [Extra Info]" -> "Title")
    cleaned_brackets = re.sub(r'\s*\[[^\]]*\]\s*', '', album_title).strip()
    if cleaned_brackets and cleaned_brackets != album_title:
        variations.append(cleaned_brackets)
        # Add normalized version
        brackets_norm = unicodedata.normalize('NFKC', cleaned_brackets)
        if brackets_norm != cleaned_brackets:
            variations.append(brackets_norm)
    
    # Extract content from brackets as alternate name (common for Japanese albums)
    bracket_match = re.search(r'\[(.*?)\]', album_title)
    if bracket_match:
        alt_name = bracket_match.group(1).strip()
        if alt_name:
            variations.append(alt_name)
            # Add normalized version
            alt_norm = unicodedata.normalize('NFKC', alt_name)
            if alt_norm != alt_name:
                variations.append(alt_norm)
    
    # Extract content from parentheses as alternate name
    paren_match = re.search(r'\((.*?)\)', album_title)
    if paren_match:
        alt_name = paren_match.group(1).strip()
        if alt_name:
            variations.append(alt_name)
            # Add normalized version
            alt_norm = unicodedata.normalize('NFKC', alt_name)
            if alt_norm != alt_name:
                variations.append(alt_norm)
    
    # Remove volume/part numbers (e.g., "Title, Vol. 1" -> "Title")
    volume_removed = re.sub(r',?\s*vol\.?\s*\d+', '', album_title, flags=re.IGNORECASE).strip()
    if volume_removed and volume_removed != album_title:
        variations.append(volume_removed)
        # Add normalized version
        vol_norm = unicodedata.normalize('NFKC', volume_removed)
        if vol_norm != volume_removed:
            variations.append(vol_norm)
    
    # Create a version with minimal punctuation
    minimal = re.sub(r'[^\w\s]', ' ', album_title)
    minimal = re.sub(r'\s+', ' ', minimal).strip()
    if minimal and minimal != album_title:
        variations.append(minimal)
        # Add normalized version
        minimal_norm = unicodedata.normalize('NFKC', minimal)
        if minimal_norm != minimal:
            variations.append(minimal_norm)
    
    # For text that might contain both Unicode and ASCII, try decomposed forms
    try:
        # NFD normalization (decomposed form) - useful for some Unicode edge cases
        nfd_normalized = unicodedata.normalize('NFD', album_title)
        if nfd_normalized != album_title and nfd_normalized != normalized:
            variations.append(nfd_normalized)
    except:
        pass
    
    # Remove empty strings and duplicates while preserving order
    seen = set()
    result = []
    for var in variations:
        var_clean = var.strip()
        if var_clean and var_clean not in seen:
            seen.add(var_clean)
            result.append(var_clean)
    
    return result

def connect_to_plex():
    """Connect to Plex server and get music library with optimized timeouts."""
    try:
        print(f"🔌 Connecting to Plex server at {PLEX_URL}...")
        
        # Create session with SSL verification disabled and longer timeouts
        session = requests.Session()
        session.verify = False
        
        # Set longer timeouts to prevent connection issues
        # (connect_timeout, read_timeout)
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

def load_metadata_cache():
    """Load album metadata from cache file."""
    if not os.path.exists(CACHE_FILE):
        print(f"❌ Cache file {CACHE_FILE} not found!")
        print("Run 'python review_genres.py' first to create the cache.")
        return None
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        timestamp = datetime.fromisoformat(cache_data["timestamp"])
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600
        
        print(f"📁 Found cached metadata from {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Cache age: {age_hours:.1f} hours")
        print(f"   Cached albums: {cache_data['total_albums']}")
        
        return cache_data["albums"]
    except Exception as e:
        print(f"❌ Error loading cache: {e}")
        return None

def get_live_plex_albums(music_library):
    """Get album metadata directly from Plex."""
    try:
        print("📡 Fetching albums directly from Plex...")
        albums = music_library.albums()
        
        album_data = []
        for album in albums:
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
        
    except Exception as e:
        print(f"❌ Error saving cache: {e}")

def load_rym_data():
    """Load RYM data directly from Firebase Realtime Database."""
    try:
        print("🔥 Connecting to Firebase Realtime Database...")
        
        # Test connection first
        test_response = requests.get(f"{FIREBASE_URL}.json?shallow=true", timeout=10)
        if test_response.status_code != 200:
            print(f"❌ Firebase connection failed: HTTP {test_response.status_code}")
            return None
        
        print("✅ Firebase connection successful")
        print("📡 Downloading RYM data from Firebase...")
        
        # Download all release data
        response = requests.get(f"{FIREBASE_URL}releases.json", timeout=120)
        
        if response.status_code != 200:
            print(f"❌ Failed to download data: HTTP {response.status_code}")
            return None
        
        firebase_data = response.json()
        
        if not firebase_data:
            print("⚠️  No data found in Firebase")
            return None
        
        # Convert Firebase nested structure to flat list format
        # Firebase structure: releases/[artist]/[album]
        rym_data = []
        total_processed = 0
        
        for artist_slug, albums in firebase_data.items():
            if not isinstance(albums, dict):
                continue
                
            artist_count = 0
            artist_name = artist_slug  # Default fallback
            
            for album_slug, album_data in albums.items():
                if isinstance(album_data, dict):
                    # Extract data from Firebase format
                    artist_name = album_data.get('artistName', '')
                    album_title = album_data.get('releaseTitle', '')
                    
                    if not artist_name or not album_title:
                        continue  # Skip entries without required fields
                    
                    primary_genres = album_data.get('genres', [])
                    secondary_genres = album_data.get('secondaryGenres', [])
                    descriptors = album_data.get('descriptors', [])
                    
                    # Convert to DataFrame-compatible format
                    rym_data.append({
                        'artist_name': artist_name,
                        'release_name': album_title,
                        'primary_genres': ', '.join(primary_genres) if primary_genres else 'NA',
                        'secondary_genres': ', '.join(secondary_genres) if secondary_genres else 'NA',
                        'descriptors': ', '.join(descriptors) if descriptors else 'NA',
                        'source': 'firebase'
                    })
                    
                    artist_count += 1
                    total_processed += 1
                    
                    # Update artist name from the first valid release
                    if artist_count == 1 and artist_name:
                        artist_name = artist_name
            
            if artist_count > 0:
                print(f"   🎵 {artist_name}: {artist_count} releases")
        
        print(f"✅ Downloaded and processed {total_processed} releases from Firebase")
        return pd.DataFrame(rym_data)
        
    except requests.exceptions.Timeout:
        print("❌ Firebase request timed out. Please check your internet connection.")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to Firebase. Please check your internet connection.")
        return None
    except Exception as e:
        print(f"❌ Error loading RYM data from Firebase: {e}")
        import traceback
        print(f"   Debug info: {traceback.format_exc()}")
        return None

def find_rym_match(artist: str, album: str, rym_data: pd.DataFrame):
    """Find matching RYM data for an album using sophisticated matching algorithm."""
    # Configuration (could be made configurable later)
    similarity_threshold = 0.8
    flexible_artist_matching = True
    title_match_threshold = 0.95
    
    # Try exact match first
    exact_match = rym_data[
        (rym_data['artist_name'].str.lower() == artist.lower()) &
        (rym_data['release_name'].str.lower() == album.lower())
    ]
    
    if not exact_match.empty:
        match_data = exact_match.iloc[0].to_dict()
        match_data['match_type'] = 'exact'
        match_data['plex_artist'] = artist
        match_data['plex_album'] = album
        return match_data
    
    # Generate variations for better matching
    artist_variations = get_artist_variations(artist)
    album_variations = get_album_variations(album)
    
    best_match = None
    best_score = 0
    debug_info = []
    
    for _, row in rym_data.iterrows():
        if not (isinstance(row['artist_name'], str) and isinstance(row['release_name'], str)):
            continue
        
        rym_artist = row['artist_name']
        rym_album = row['release_name']
        
        # Generate variations for RYM data too
        rym_artist_variations = get_artist_variations(rym_artist)
        rym_album_variations = get_album_variations(rym_album)
        
        # Calculate similarity scores for each artist variation
        best_artist_score = 0
        for artist_var in artist_variations:
            for rym_artist_var in rym_artist_variations:
                artist_score = string_similarity(artist_var, rym_artist_var)
                best_artist_score = max(best_artist_score, artist_score)
        
        # Calculate similarity scores for each album title variation
        best_title_score = 0
        for album_var in album_variations:
            for rym_album_var in rym_album_variations:
                title_score = string_similarity(album_var, rym_album_var)
                best_title_score = max(best_title_score, title_score)
        
        combined_score = (best_artist_score + best_title_score) / 2
        
        # Store debug info for potential high title matches with low artist matches
        if best_title_score > 0.9 and best_artist_score < 0.3:
            debug_info.append({
                'artist': f"'{artist}' vs '{rym_artist}'",
                'album': f"'{album}' vs '{rym_album}'",
                'artist_score': best_artist_score,
                'title_score': best_title_score,
                'combined': combined_score
            })
        
        # Standard matching
        if combined_score > best_score and combined_score >= similarity_threshold:
            best_score = combined_score
            best_match = row.to_dict()
            best_match['match_type'] = 'fuzzy'
            best_match['plex_artist'] = artist
            best_match['plex_album'] = album
            best_match['similarity_score'] = combined_score
        # Flexible artist matching for high title similarity
        elif (flexible_artist_matching and 
              best_title_score >= title_match_threshold and 
              best_artist_score < similarity_threshold):
            if combined_score > best_score:
                best_score = combined_score
                best_match = row.to_dict()
                best_match['match_type'] = 'flexible'
                best_match['plex_artist'] = artist
                best_match['plex_album'] = album
                best_match['similarity_score'] = combined_score
                # Add note about flexible matching
                best_match['flexible_match_note'] = f"High title match (title: {best_title_score:.3f}, artist: {best_artist_score:.3f})"
    
    if best_match:
        if best_match['match_type'] == 'flexible':
            print(f"      🤔 Flexible match: {best_match.get('flexible_match_note', '')}")
        return best_match
    
    # Print debug info for interesting near-misses
    if debug_info:
        print(f"      🔍 Found {len(debug_info)} high title matches with low artist similarity:")
        for info in debug_info[:3]:  # Show first 3
            print(f"         {info['artist']} | {info['album']} (artist: {info['artist_score']:.3f}, title: {info['title_score']:.3f})")
    
    # Try album-only matching as fallback
    album_matches = rym_data[rym_data['release_name'].str.lower() == album.lower()]
    
    if not album_matches.empty:
        # Skip album-only matching for very common album titles that are likely to produce false matches
        common_titles = ['live', 'greatest hits', 'best of', 'compilation', 'the best of']
        if album.lower().strip() in common_titles:
            return None
        
        # If multiple matches, pick the first one (could be improved with additional logic)
        match_data = album_matches.iloc[0].to_dict()
        match_data['match_type'] = 'album_only'
        match_data['plex_artist'] = artist
        match_data['plex_album'] = album
        return match_data
    
    return None

def generate_rym_url(artist: str, album: str) -> str:
    """Generate an optimistic RYM URL for an artist and album."""
    def to_slug(text: str) -> str:
        """Convert text to URL-friendly slug."""
        # Convert to lowercase
        slug = text.lower()
        
        # Replace common characters and patterns
        slug = re.sub(r'[&]', 'and', slug)  # & -> and
        slug = re.sub(r'[^\w\s-]', '', slug)  # Remove special chars except spaces and hyphens
        slug = re.sub(r'[-\s]+', '-', slug)  # Replace spaces and multiple hyphens with single hyphen
        slug = slug.strip('-')  # Remove leading/trailing hyphens
        
        return slug
    
    artist_slug = to_slug(artist)
    album_slug = to_slug(album)
    
    return f"https://rateyourmusic.com/release/album/{artist_slug}/{album_slug}/"

def process_rym_genres(rym_match: dict, hierarchy: RYMGenreHierarchy, valid_descriptors: set = None):
    """Process RYM data into genres, styles, and moods with descriptor correction.
    
    Updated structure:
    - genres: Primary RYM genres + hierarchical expansion
    - styles: Primary + secondary RYM genres (no expansion)
    - moods: Descriptors (with correction)
    """
    genres = set()
    styles = set()
    moods = set()
    
    # Collect primary genres
    primary_genres = []
    if pd.notna(rym_match.get('primary_genres')) and rym_match['primary_genres']:
        primary_genres_str = str(rym_match['primary_genres']).strip()
        if primary_genres_str.upper() != 'NA':
            primary_genres = [genre.strip() for genre in primary_genres_str.split(',')]
            primary_genres = [title_case_tag(genre) for genre in primary_genres if genre and genre.upper() != 'NA']
    
    # Collect secondary genres
    secondary_genres = []
    if pd.notna(rym_match.get('secondary_genres')) and rym_match['secondary_genres']:
        secondary_genres_str = str(rym_match['secondary_genres']).strip()
        if secondary_genres_str.upper() != 'NA':
            secondary_genres = [genre.strip() for genre in secondary_genres_str.split(',')]
            secondary_genres = [title_case_tag(genre) for genre in secondary_genres if genre and genre.upper() != 'NA']
    
    # Process genres: Primary genres + hierarchical expansion
    if primary_genres:
        expanded_genres = hierarchy.expand_genres_hierarchically(primary_genres)
        genres.update(expanded_genres)
    
    # Process styles: Primary + secondary genres (no expansion)
    styles.update(primary_genres)
    styles.update(secondary_genres)
    
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
    
    return genres, styles, moods

def metadata_already_matches(album_data: dict, new_genres: set, new_styles: set, new_moods: set) -> bool:
    """Check if the album's current metadata already contains all RYM data.
    
    Unlike exact matching, this checks if all RYM tags are already present in Plex.
    Plex can have additional tags beyond RYM - that's fine and we'll skip the update.
    """
    # Get current metadata from album data (normalize case for comparison)
    current_genres = set(genre.lower().strip() for genre in album_data.get('genres', []))
    current_styles = set(style.lower().strip() for style in album_data.get('styles', []))
    current_moods = set(mood.lower().strip() for mood in album_data.get('moods', []))
    
    # Convert RYM metadata to normalized sets for comparison
    target_genres = set(genre.lower().strip() for genre in new_genres) if new_genres else set()
    target_styles = set(style.lower().strip() for style in new_styles) if new_styles else set()
    target_moods = set(mood.lower().strip() for mood in new_moods) if new_moods else set()
    
    # Check if all RYM tags are already present in Plex
    genres_covered = True #target_genres.issubset(current_genres)
    styles_covered = target_styles.issubset(current_styles)
    moods_covered = target_moods.issubset(current_moods)
    
    return genres_covered and styles_covered and moods_covered

def update_plex_album(music_library, album_data: dict, new_genres: set, new_styles: set, new_moods: set, dry_run: bool = True):
    """Update a Plex album with new metadata (assumes metadata has been pre-cleared)."""
    try:
        if dry_run:
            print(f"   🔍 DRY RUN - Would update {album_data['title']}:")
            print(f"      Add {len(new_genres)} genres: {sorted(list(new_genres)[:5])}{'...' if len(new_genres) > 5 else ''}")
            print(f"      Add {len(new_styles)} styles: {sorted(list(new_styles)[:5])}{'...' if len(new_styles) > 5 else ''}")
            print(f"      Add {len(new_moods)} moods: {sorted(list(new_moods)[:5])}{'...' if len(new_moods) > 5 else ''}")
            return True
        
        # Get the actual Plex album object
        album = music_library.fetchItem(album_data['key'])
        
        # Convert sets to sorted lists for consistency
        new_genres_list = sorted(list(new_genres)) if new_genres else []
        new_styles_list = sorted(list(new_styles)) if new_styles else []
        new_moods_list = sorted(list(new_moods)) if new_moods else []
        
        # Add new genres
        if new_genres_list:
            album.addGenre(new_genres_list, locked=True)
        
        # Add new styles
        if new_styles_list:
            album.addStyle(new_styles_list, locked=True)
        
        # Add new moods
        if new_moods_list:
            album.addMood(new_moods_list, locked=True)
        
        print(f"   ✅ Updated {album.title}")
        print(f"      Added {len(new_genres)} genres, {len(new_styles)} styles, {len(new_moods)} moods")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error updating {album_data['title']}: {e}")
        return False

def update_plex_albums_batch(music_library, albums_to_update: list, batch_size: int = 50):
    """Update a batch of Plex albums."""
    if not albums_to_update:
        return 0, 0
    
    updated_count = 0
    error_count = 0
    total_albums = len(albums_to_update)
    
    print(f"\n🔄 Processing {total_albums} albums in batches of {batch_size}...")
    
    for i in range(0, total_albums, batch_size):
        batch = albums_to_update[i:i + batch_size]
        print(f"\n📦 Processing batch {i//batch_size + 1}/{(total_albums + batch_size - 1)//batch_size}")
        
        for album_entry in batch:
            try:
                # Extract the nested data structure
                album_data = album_entry['album_data']
                genres = album_entry['genres']
                styles = album_entry['styles']
                moods = album_entry['moods']
                
                # Get the album from Plex using fetchItem (consistent with update_plex_album)
                album = music_library.fetchItem(album_data['key'])
                if not album:
                    print(f"❌ Album not found in Plex: {album_data['artist']} - {album_data['title']}")
                    error_count += 1
                    continue
                
                # Update the album
                success = update_plex_album(music_library, album_data, genres, styles, moods, dry_run=False)
                if success:
                    updated_count += 1
                else:
                    error_count += 1
                
            except Exception as e:
                # Handle the nested structure for error reporting
                try:
                    album_data = album_entry['album_data']
                    print(f"❌ Error updating album {album_data['artist']} - {album_data['title']}: {e}")
                except:
                    print(f"❌ Error updating album (unknown details): {e}")
                error_count += 1
        
        if i + batch_size < total_albums:
            print(f"   ⏸️  Batch complete. Waiting 2 seconds before next batch...")
            time.sleep(2)
    
    return updated_count, error_count

def load_rym_descriptor_tree():
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
                    descriptors.add(node['name'].lower())
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

def correct_descriptor_name(descriptor: str, valid_descriptors: set) -> str:
    """Correct descriptor names using the RYM descriptor tree as source of truth.
    Returns None if descriptor is invalid and cannot be corrected."""
    if not descriptor or not valid_descriptors:
        return descriptor
    
    descriptor_clean = descriptor.strip().lower()
    original_descriptor = descriptor.strip()
    
    # Direct match - already correct
    if descriptor_clean in valid_descriptors:
        # Find the original case version
        for valid_desc in valid_descriptors:
            if valid_desc.lower() == descriptor_clean:
                return title_case_tag(valid_desc)
        return title_case_tag(descriptor)
    
    # Common corrections based on known issues
    corrections = {
        'malevocals': 'male vocalist',
        'male vocals': 'male vocalist', 
        'femalevocals': 'female vocalist',
        'female vocals': 'female vocalist',
        'conceptalbum': 'concept album',
        'uncommontimesignatures': 'uncommon time signatures',
        'sciencefiction': 'science fiction',
        'androgynousvocals': 'androgynous vocals',
        'rockopera': 'rock opera',
        'wallof sound': 'wall of sound',
        'vocalgroup': 'vocal group',
        'chambermusic': 'chamber music',
        'generativemusic': 'generative music',
        'fairytale': 'fairy tale',
        'acappella': 'a cappella',
        'lgbt': 'LGBTQ',
        # Add more corrections as needed
    }
    
    if descriptor_clean in corrections:
        corrected = corrections[descriptor_clean]
        if corrected.lower() in valid_descriptors:
            corrected_title = title_case_tag(corrected)
            if original_descriptor.lower() != corrected.lower():
                print(f"      🔧 Corrected descriptor: '{original_descriptor}' → '{corrected_title}'")
            return corrected_title
    
    # Try fuzzy matching for close matches
    from difflib import get_close_matches
    close_matches = get_close_matches(descriptor_clean, valid_descriptors, n=1, cutoff=0.8)
    if close_matches:
        corrected_title = title_case_tag(close_matches[0])
        if original_descriptor.lower() != close_matches[0].lower():
            print(f"      🔧 Fuzzy corrected descriptor: '{original_descriptor}' → '{corrected_title}'")
        return corrected_title
    
    # If no correction found, exclude this descriptor from metadata
    print(f"      ❌ Excluding invalid descriptor: '{original_descriptor}' (not found in RYM tree)")
    return None

def main():
    """Main function."""
    import sys
    
    # Check for help
    if "--help" in sys.argv or "-h" in sys.argv:
        print("🎵 RYM Plex Metadata Updater")
        print("=" * 50)
        print("Updates Plex music library metadata using RYM data from Firebase with hierarchical genre expansion.")
        print()
        print("Usage:")
        print("  python rym_plex_updater.py [options]")
        print()
        print("Options:")
        print("  --execute          Actually apply changes (default is dry run)")
        print("  --live             Fetch albums directly from Plex instead of using cache")
        print("  --export-missing   Export list of albums not found in RYM data")
        print("  --batch-size N     Process albums in batches of N (default: 50)")
        print("  --limit N          Only process first N albums (for testing)")
        print("  --force            Update all albums, even if they already have all RYM metadata")
        print("  --help, -h         Show this help message")
        print()
        print("Examples:")
        print("  # Dry run using cached album data")
        print("  python rym_plex_updater.py")
        print()
        print("  # Test with first 10 albums only")
        print("  python rym_plex_updater.py --limit 10")
        print()
        print("  # Actually apply changes using live Plex data")
        print("  python rym_plex_updater.py --execute --live")
        print()
        print("  # Use smaller batches for slower Plex servers")
        print("  python rym_plex_updater.py --execute --batch-size 25")
        print()
        print("  # Export missing albums list")
        print("  python rym_plex_updater.py --export-missing")
        print()
        print("  # Force update all albums (ignore existing RYM metadata)")
        print("  python rym_plex_updater.py --execute --force")
        print()
        print("Recommended Workflow:")
        print("  1. python clear_plex_metadata.py --execute")
        print("  2. python review_genres.py")
        print("  3. python rym_plex_updater.py --execute")
        print()
        print("Performance Tips:")
        print("  • Use --batch-size 25 for slower Plex servers or networks")
        print("  • Use --batch-size 100 for faster Plex servers")
        print("  • Clear metadata first with clear_plex_metadata.py for best performance")
        print("  • Albums with all RYM metadata already present are automatically skipped")
        print()
        print("Data Processing:")
        print("  • Primary genres → Genres (with hierarchical expansion)")
        print("  • Secondary genres → Styles (no expansion)")
        print("  • Descriptors → Moods (with automatic correction using RYM tree)")
        print("  • Queries RYM data directly from Firebase Realtime Database")
        print("  • Invalid descriptors not in RYM tree are excluded")
        print("  • Assumes metadata has been pre-cleared for clean application")
        print("  • Albums already up-to-date are automatically skipped")
        print("  • Album-only matches are processed automatically")
        return
    
    print("🎵 RYM Plex Metadata Updater")
    print("=" * 50)
    
    execute = "--execute" in sys.argv
    use_live = "--live" in sys.argv
    export_missing = "--export-missing" in sys.argv
    force_update = "--force" in sys.argv
    
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
        print("   Use --execute to actually apply changes")
    
    if force_update:
        print("💪 FORCE MODE - All albums will be updated regardless of existing RYM metadata")
    else:
        print("📋 SKIP MODE - Albums with existing RYM metadata will be skipped (use --force to override)")
    
    print()
    
    # Initialize RYM genre hierarchy
    print("🌳 Loading RYM genre hierarchy...")
    hierarchy = RYMGenreHierarchy()
    if not hierarchy.all_genres:
        print("❌ Failed to load RYM genre hierarchy")
        return
    
    # Load RYM descriptor tree for correction
    print("📝 Loading RYM descriptor tree...")
    valid_descriptors = load_rym_descriptor_tree()
    
    # Load RYM data
    print("\n📊 Loading RYM data...")
    rym_data = load_rym_data()
    if rym_data is None:
        return
    
    # Load album data
    print("\n📚 Loading album data...")
    if use_live:
        plex, music_library = connect_to_plex()
        if not music_library:
            return
        albums_data = get_live_plex_albums(music_library)
        save_metadata_cache(albums_data)
    else:
        albums_data = load_metadata_cache()
        music_library = None
    
    if not albums_data:
        return
    
    # Apply limit if specified for testing
    if limit:
        original_count = len(albums_data)
        albums_data = albums_data[:limit]
        print(f"🧪 Testing mode: Processing first {len(albums_data)} of {original_count} albums (--limit {limit})")
    
    # Process albums
    print(f"\n🔄 Processing {len(albums_data)} albums...")
    
    matched_albums = []
    missing_albums = []
    album_only_matches = []
    fuzzy_matches = []
    skipped_albums = 0  # Track albums that are already up to date
    exact_matches_to_update = 0  # Track exact matches that need updating
    fuzzy_matches_to_update = 0  # Track fuzzy matches that need updating
    flexible_matches_to_update = 0  # Track flexible matches that need updating
    album_only_matches_to_update = 0  # Track album-only matches that need updating
    
    # First pass: Find all matches and prepare data
    for i, album_data in enumerate(albums_data, 1):
        artist = album_data.get('artist', '')
        title = album_data.get('title', '')
        
        if not artist or not title:
            continue
        
        print(f"\n[{i}/{len(albums_data)}] {artist} - {title}")
        
        # Find RYM match
        rym_match = find_rym_match(artist, title, rym_data)
        
        if rym_match:
            match_type = rym_match.get('match_type', 'unknown')
            
            if match_type == 'album_only':
                print(f"   ✅ Found album-only match: {rym_match.get('artist_name', '')} - {rym_match.get('release_name', '')}")
                album_only_matches.append({
                    'album_data': album_data,
                    'rym_match': rym_match
                })
                # Process album-only matches (they look good!)
            else:
                if match_type == 'exact':
                    print(f"   ✅ Found exact match in RYM data")
                elif match_type == 'fuzzy':
                    similarity = rym_match.get('similarity_score', 0)
                    print(f"   ✅ Found fuzzy match in RYM data (similarity: {similarity:.2f})")
                    fuzzy_matches.append({
                        'album_data': album_data,
                        'rym_match': rym_match
                    })
                elif match_type == 'flexible':
                    similarity = rym_match.get('similarity_score', 0)
                    print(f"   ✅ Found flexible match in RYM data (similarity: {similarity:.2f})")
                    print(f"      💡 {rym_match.get('flexible_match_note', '')}")
                    fuzzy_matches.append({
                        'album_data': album_data,
                        'rym_match': rym_match
                    })
            
            # Process RYM data into genres, styles, moods
            genres, styles, moods = process_rym_genres(rym_match, hierarchy, valid_descriptors)
            
            print(f"   📊 Processed: {len(genres)} genres, {len(styles)} styles, {len(moods)} moods")
            
            # Check if metadata already matches (skip if up to date unless force is enabled)
            if not force_update and metadata_already_matches(album_data, genres, styles, moods):
                print(f"   ⏭️  All RYM metadata already exists in Plex - skipping")
                skipped_albums += 1
                continue
            
            # Count matches that need updating
            if match_type == 'exact':
                exact_matches_to_update += 1
            elif match_type == 'fuzzy':
                fuzzy_matches_to_update += 1
            elif match_type == 'flexible':
                flexible_matches_to_update += 1
            elif match_type == 'album_only':
                album_only_matches_to_update += 1
            
            matched_albums.append({
                'album_data': album_data,
                'rym_match': rym_match,
                'genres': genres,
                'styles': styles,
                'moods': moods
            })
            
            # Show what would be done in dry run mode
            if not execute:
                update_plex_album(None, album_data, genres, styles, moods, dry_run=True)
        else:
            print(f"   ❌ Not found in RYM data")
            missing_albums.append(album_data)
    
    # Second pass: Apply updates using batch processing if executing
    updated_count = 0
    error_count = 0
    
    if execute and matched_albums:
        if not music_library:
            plex, music_library = connect_to_plex()
            if not music_library:
                print("❌ Cannot connect to Plex for updates")
                return
        
        # Use batch processing for better performance
        updated_count, error_count = update_plex_albums_batch(music_library, matched_albums, batch_size)
    
    # Summary
    print(f"\n📈 Processing Summary:")
    print(f"   Total albums: {len(albums_data)}")
    print(f"   Found in RYM: {len(matched_albums) + skipped_albums}")
    print(f"     - Need updating: {len(matched_albums)}")
    print(f"     - Already up to date: {skipped_albums}")
    print(f"     - Exact matches: {exact_matches_to_update}")
    print(f"     - Fuzzy matches: {fuzzy_matches_to_update}")
    print(f"     - Flexible matches: {flexible_matches_to_update}")
    print(f"     - Album-only matches: {album_only_matches_to_update}")
    print(f"   Missing from RYM: {len(missing_albums)}")
    
    if execute:
        print(f"   Successfully updated: {updated_count}")
        if error_count > 0:
            print(f"   Errors: {error_count}")
        print(f"\n💡 Run 'python review_genres.py' to refresh your cache.")
    
    if skipped_albums > 0 and not force_update:
        print(f"💡 {skipped_albums} albums were skipped because they already have all RYM metadata")
        print(f"   Use --force to update them anyway")

if __name__ == "__main__":
    main() 