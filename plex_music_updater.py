import os
import time
from typing import List, Dict, Set
from dotenv import load_dotenv
from plexapi.server import PlexServer
import pylast
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import logging
import json
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
import re
import pandas as pd
from difflib import SequenceMatcher
from rym_genre_hierarchy import RYMGenreHierarchy

# Try to import configuration
try:
    import config
except ImportError:
    print("Error: config.py not found!")
    print("Please copy config.py.example to config.py and fill in your API keys.")
    exit(1)

# Disable SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress verbose logging from external libraries
logging.getLogger('pylast').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

# Load environment variables
load_dotenv()

def title_case_tag(tag: str) -> str:
    """Convert a tag to proper title case.
    
    Rules:
    - Capitalize first letter of each word
    - Keep certain words lowercase (a, an, the, and, or, but, for, nor, on, at, to, from, by)
    - Always capitalize first and last word
    - Keep certain words uppercase (ID, UK, USA, etc.)
    - Handle slashes by capitalizing each part separately
    - Handle dashes by capitalizing each part separately
    - Special corrections for common music terms
    """
    # Special corrections for common music terms
    special_corrections = {
        'hip-hop': 'Hip Hop',
        'hiphop': 'Hip Hop',
    }
    
    # Check for special corrections first (case-insensitive)
    tag_lower = tag.lower().strip()
    if tag_lower in special_corrections:
        return special_corrections[tag_lower]
    
    # Words to keep lowercase unless they're the first or last word
    lowercase_words = {'a', 'an', 'the', 'and', 'or', 'but', 'for', 'nor', 'on', 'at', 'to', 'from', 'by', 'in', 'of'}
    
    # Words to keep uppercase
    uppercase_words = {'id', 'uk', 'usa', 'us', 'eu', 'ep', 'lp', 'cd', 'dvd', 'bluray', 'hd', '4k', 'uhd'}
    
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
            words[i] = word.upper()
        # Keep certain words lowercase unless they're first or last
        elif word_lower in lowercase_words and i != 0 and i != len(words) - 1:
            words[i] = word_lower
        # Capitalize other words
        else:
            words[i] = word.capitalize()
    
    return ' '.join(words)

def string_similarity(a: str, b: str) -> float:
    """Calculate string similarity ratio between two strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

class MusicMetadataUpdater:
    def __init__(self):
        # Initialize Plex connection
        self.plex_url = config.PLEX_URL
        self.plex_token = config.PLEX_TOKEN
        
        # Create a session with SSL verification disabled
        session = requests.Session()
        session.verify = False
        
        # Initialize Plex server with the custom session
        self.plex = PlexServer(self.plex_url, self.plex_token, session=session)

        # Initialize Last.fm connection
        self.lastfm = pylast.LastFMNetwork(
            api_key=config.LASTFM_API_KEY,
            api_secret=config.LASTFM_API_SECRET
        )

        # Initialize Spotify connection
        self.spotify = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=config.SPOTIFY_CLIENT_ID,
                client_secret=config.SPOTIFY_CLIENT_SECRET
            )
        )
        
        # Load Pitchfork data
        try:
            self.pitchfork_data = pd.read_csv('data/pitchfork.csv')
            # Clean up the data
            self.pitchfork_data['artist'] = self.pitchfork_data['artist'].str.strip()
            self.pitchfork_data['album'] = self.pitchfork_data['album'].str.strip()
            self.pitchfork_data['genre'] = self.pitchfork_data['genre'].str.strip()
            logger.info(f"Loaded {len(self.pitchfork_data)} Pitchfork reviews")
        except FileNotFoundError:
            logger.warning("pitchfork.csv not found in data/ directory. Pitchfork data will be unavailable.")
            self.pitchfork_data = pd.DataFrame()

        # Load RYM data
        try:
            self.rym_data = pd.read_csv('data/rym.csv')
            # Clean up the data
            self.rym_data['artist_name'] = self.rym_data['artist_name'].str.strip()
            self.rym_data['release_name'] = self.rym_data['release_name'].str.strip()
            self.rym_data['primary_genres'] = self.rym_data['primary_genres'].str.strip()
            self.rym_data['secondary_genres'] = self.rym_data['secondary_genres'].str.strip()
            logger.info(f"Loaded {len(self.rym_data)} RYM albums")
        except FileNotFoundError:
            logger.warning("rym.csv not found in data/ directory. RYM data will be unavailable.")
            self.rym_data = pd.DataFrame()

        # Load Rolling Stone data
        try:
            self.rolling_stone_data = pd.read_csv('data/rolling-stone.csv')
            # Clean up the data and remove quotes from album names
            self.rolling_stone_data['Artist'] = self.rolling_stone_data['Artist'].str.strip()
            self.rolling_stone_data['Album Name'] = self.rolling_stone_data['Album Name'].str.strip().str.strip("'\"")
            logger.info(f"Loaded {len(self.rolling_stone_data)} Rolling Stone albums")
        except FileNotFoundError:
            logger.warning("rolling-stone.csv not found in data/ directory. Rolling Stone data will be unavailable.")
            self.rolling_stone_data = pd.DataFrame()

        # Initialize RYM genre hierarchy
        self.rym_hierarchy = RYMGenreHierarchy()
        logger.info(f"RYM hierarchy loaded with {len(self.rym_hierarchy.all_genres)} valid genres")

        # Get all existing genres from Plex
        self.existing_plex_genres = self.get_all_plex_genres()
        logger.info(f"Found {len(self.existing_plex_genres)} existing genres in Plex: {sorted(self.existing_plex_genres)}")

        # Track albums with no data found
        self.albums_no_data = []

    def get_all_plex_genres(self) -> Set[str]:
        """Get all existing genres from the Plex music library."""
        try:
            music_library = self.plex.library.section('Music')
            # Get all albums and collect their genres
            albums = music_library.albums()
            genre_names = set()
            
            for album in albums:
                if album.genres:
                    for genre in album.genres:
                        genre_names.add(genre.tag.lower())
            
            return genre_names
        except Exception as e:
            logger.error(f"Error fetching existing Plex genres: {e}")
            return set()

    def get_pitchfork_data(self, artist: str, album: str) -> Dict:
        """Get Pitchfork data for an album if it exists."""
        if self.pitchfork_data.empty:
            return None
            
        # Try exact match first
        exact_match = self.pitchfork_data[
            (self.pitchfork_data['artist'].apply(lambda x: isinstance(x, str) and x.lower() == artist.lower())) &
            (self.pitchfork_data['album'].apply(lambda x: isinstance(x, str) and x.lower() == album.lower()))
        ]
        
        if not exact_match.empty:
            return exact_match.iloc[0].to_dict()
        
        # Try fuzzy matching if no exact match
        best_match = None
        best_score = 0.8  # Minimum similarity threshold
        
        for _, row in self.pitchfork_data.iterrows():
            # Only compare if both artist and album are strings
            if not (isinstance(row['artist'], str) and isinstance(row['album'], str)):
                continue
            artist_similarity = string_similarity(artist, row['artist'])
            album_similarity = string_similarity(album, row['album'])
            
            # Calculate combined similarity score
            similarity_score = (artist_similarity + album_similarity) / 2
            
            if similarity_score > best_score:
                best_score = similarity_score
                best_match = row.to_dict()
        
        return best_match if best_match else None

    def get_rym_data(self, artist: str, album: str) -> Dict:
        """Get RYM data for an album if it exists."""
        if self.rym_data.empty:
            return None
            
        # Try exact match first
        exact_match = self.rym_data[
            (self.rym_data['artist_name'].str.lower() == artist.lower()) &
            (self.rym_data['release_name'].str.lower() == album.lower())
        ]
        
        if not exact_match.empty:
            return exact_match.iloc[0].to_dict()
        
        # Try fuzzy matching if no exact match
        best_match = None
        best_score = 0.8  # Minimum similarity threshold
        
        for _, row in self.rym_data.iterrows():
            # Only compare if both artist and album are strings
            if not (isinstance(row['artist_name'], str) and isinstance(row['release_name'], str)):
                continue
            artist_similarity = string_similarity(artist, row['artist_name'])
            album_similarity = string_similarity(album, row['release_name'])
            
            # Calculate combined similarity score
            similarity_score = (artist_similarity + album_similarity) / 2
            
            if similarity_score > best_score:
                best_score = similarity_score
                best_match = row.to_dict()
        
        return best_match if best_match else None

    def get_rolling_stone_data(self, artist: str, album: str) -> bool:
        """Check if an album exists in the Rolling Stone Top 500 list."""
        if self.rolling_stone_data.empty:
            return False
            
        # Try exact match first
        exact_match = self.rolling_stone_data[
            (self.rolling_stone_data['Artist'].str.lower() == artist.lower()) &
            (self.rolling_stone_data['Album Name'].str.lower() == album.lower())
        ]
        
        if not exact_match.empty:
            return True
        
        # Try fuzzy matching if no exact match
        for _, row in self.rolling_stone_data.iterrows():
            # Only compare if both artist and album are strings
            if not (isinstance(row['Artist'], str) and isinstance(row['Album Name'], str)):
                continue
            artist_similarity = string_similarity(artist, row['Artist'])
            album_similarity = string_similarity(album, row['Album Name'])
            
            # Calculate combined similarity score
            similarity_score = (artist_similarity + album_similarity) / 2
            
            if similarity_score > 0.8:  # Same threshold as other sources
                return True
        
        return False

    def get_lastfm_tags(self, artist: str, album: str) -> tuple[Set[str], Set[str]]:
        """Get tags from Last.fm for an album. Returns (genres, styles)."""
        try:
            # Skip artist fallback for generic artist names
            generic_artists = {'various artists', 'various', 'compilation', 'soundtrack', 'va', 'unknown artist', 'unknown'}
            
            # Try to get album tags first
            try:
                album_obj = self.lastfm.get_album(artist, album)
                tags = album_obj.get_top_tags(limit=10)
                logger.info(f"Found {len(tags)} tags for album {album} by {artist} on Last.fm")
                if len(tags) == 0:
                    raise Exception("No tags found for album")
            except Exception as album_error:
                # Album not found, try getting artist tags instead (unless it's a generic artist)
                if artist.lower() in generic_artists:
                    logger.info(f"Skipping artist search for generic artist: {artist}")
                    return set(), set()
                
                logger.info(f"Album not found on Last.fm, searching for artist: {artist}")
                try:
                    artist_obj = self.lastfm.get_artist(artist)
                    tags = artist_obj.get_top_tags(limit=10)
                except Exception as artist_error:
                    logger.warning(f"Artist {artist} not found on Last.fm")
                    return set(), set()
            
            # Filter out unwanted tags
            filtered_tags = []
            skip_patterns = [
                r'^\d{4}$',  # Year (4 digits)
                r'^\d{4}s$',  # Year (4 digits)s
                r'^\d{2}s$',  # Decade (e.g., "00s", "10s")
                r'^\d{4}:',   # Year with colon (e.g., "2014: eps")
                r'best of',   # Best of collections
                r'albums i own',
                r'my collection',
                r'favorites',
                r'favourites',
                r'owned',
                r'collection',
                r'library',
                r'cd',
                r'vinyl',
                r'digital',
                r'physical',
                r'rip',
                r'import',
                r'own',
                r'have',
                r'got',
                r'listened',
                r'heard',
                r'seen live',
                r'seen',
                r'live',
                r'concert',
                r'tour',
                r'seen in concert',
                r'seen in',
                r'seen at',
                r'seen on',
                r'seen with',
                r'seen by',
                r'seen as',
                r'seen like',
                r'seen as a',
                r'seen as an',
                r'seen as the',
                r'seen as this',
                r'seen as that',
                r'seen as these',
                r'seen as those',
                r'seen as my',
                r'seen as your',
                r'seen as his',
                r'seen as her',
                r'seen as its',
                r'seen as our',
                r'seen as their',
                r'seen as mine',
                r'seen as yours',
                r'seen as his',
                r'seen as hers',
                r'seen as its',
                r'seen as ours',
                r'seen as theirs',
                r'wishlist',
                r'wishlist',
                # Country and region tags
                r'usa',
                r'united states',
                r'uk',
                r'united kingdom',
                r'england',
                r'scotland',
                r'wales',
                r'northern ireland',
                r'europe',
                r'american',
                r'america',
                r'british',
                r'canadian',
                r'australian',
                r'japanese',
                r'korean',
                r'chinese',
                r'french',
                r'german',
                r'italian',
                r'spanish',
                r'portuguese',
                r'russian',
                r'brazilian',
                r'mexican',
                r'african',
                r'asian',
                r'european',
                r'japan',
                r'scottish',
                r'icelandic',
                r'irish',
                r'irlandic',
                r'irish',
                r'warp',
                r'swedish',
                r'pedo',
                r'pedophile',
                r'autotune',
                r'croatian',
                r'listen',
                r'male',
                r'female',
                # Common non-descriptive words
                r'album',
                r'albums',
                r'record',
                r'records',
                r'release',
                r'releases',
                r'track',
                r'tracks',
                r'song',
                r'songs',
                r'music',
                r'musician',
                r'musicians',
                r'band',
                r'bands',
                r'artist',
                r'artists',
                r'group',
                r'groups',
                r'duo',
                r'trio',
                r'quartet',
                r'quintet',
                r'sextet',
                r'septet',
                r'octet',
                r'nonet',
                r'orchestra',
                r'choir',
                r'ensemble',
                r'project',
                r'projects',
                r'label',
                r'labels',
                r'studio',
                r'studios',
                r'live album',
                r'studio album',
                r'compilation',
                r'compilations',
                r'box set',
                r'box sets',
                r'remaster',
                r'remastered',
                r'reissue',
                r'reissues',
                r'deluxe',
                r'edition',
                r'editions',
                r'version',
                r'versions',
                r'remix',
                r'remixes',
                r'cover',
                r'covers',
                r'tribute',
                r'tributes',
                r'original',
                r'originals',
                r'classic',
                r'classics',
                r'essential',
                r'essentials',
                r'best of',
                r'greatest hits',
                r'collection',
                r'collections',
                r'anthology',
                r'anthologies',
                r'archive',
                r'archives',
                r'rarities',
                r'b-sides',
                r'demos',
                r'unreleased',
                r'outtakes',
                r'sessions',
                r'bootleg',
                r'bootlegs',
                r'promo',
                r'promos',
                r'single',
                r'singles',
                r'ep',
                r'eps',
                r'lp',
                r'lps',
                r'cd',
                r'cds',
                r'vinyl',
                r'cassette',
                r'cassettes',
                r'tape',
                r'tapes',
                r'digital',
                r'download',
                r'downloads',
                r'stream',
                r'streams',
                r'streaming',
                r'online',
                r'internet',
                r'web',
                r'website',
                r'webpage',
                r'blog',
                r'blogs',
                r'forum',
                r'forums',
                r'social',
                r'social media',
                r'facebook',
                r'twitter',
                r'instagram',
                r'youtube',
                r'spotify',
                r'apple music',
                r'itunes',
                r'bandcamp',
                r'soundcloud',
                r'last.fm',
                r'lastfm',
                r'rateyourmusic',
                r'rym',
                r'discogs',
                r'wikipedia',
                r'wiki',
                # Subjective/opinion tags
                r'faves',
                r'wonderful',
                r'laid back',
                r'wow',
                r'guitar',
                r'insane',
                r'amazing',
                r'awesome',
                r'brilliant',
                r'excellent',
                r'fantastic',
                r'great',
                r'good',
                r'bad',
                r'terrible',
                r'awful',
                r'perfect',
                r'beautiful',
                r'gorgeous',
                r'stunning',
                r'incredible',
                r'outstanding',
                r'superb',
                r'magnificent',
                r'marvelous',
                r'wonderful',
                r'fabulous',
                r'spectacular',
                r'phenomenal',
                r'extraordinary',
                r'remarkable',
                r'impressive',
                r'breathtaking',
                r'mind-blowing',
                r'epic',
                r'legendary',
                r'iconic',
                r'timeless',
                r'masterpiece',
                r'genius',
                r'brilliant',
                r'flawless',
                r'perfect',
                r'love',
                r'hate',
                r'like',
                r'dislike',
                r'favorite',
                r'favourite',
                r'best',
                r'worst',
                r'top',
                r'bottom',
                r'number one',
                r'#1',
                r'cool',
                r'hot',
                r'fire',
                r'sick',
                r'dope',
                r'fresh',
                r'tight',
                r'solid',
                r'decent',
                r'okay',
                r'alright',
                r'meh',
                r'boring',
                r'dull',
                r'bland',
                r'generic',
                r'overrated',
                r'underrated',
                r'overhyped',
                r'underappreciated',
                # Vague mood/feeling tags
                r'chill',
                r'surreal',
                r'warm',
                r'cold',
                r'dark',
                r'light',
                r'heavy',
                r'soft',
                r'hard',
                r'smooth',
                r'rough',
                r'dreamy',
                r'atmospheric',
                r'moody',
                r'emotional',
                r'intense',
                r'relaxing',
                r'energetic',
                r'mellow',
                r'upbeat',
                r'downtempo',
                r'uplifting',
                r'depressing',
                r'sad',
                r'happy',
                r'angry',
                r'peaceful',
                r'aggressive',
                r'gentle',
                r'powerful',
                r'weak',
                r'strong',
                r'deep',
                r'shallow',
                r'rich',
                r'thin',
                r'thick',
                r'dense',
                r'sparse',
                r'full',
                r'empty',
                r'bright',
                r'dull',
                r'sharp',
                r'blunt',
                r'clear',
                r'muddy',
                r'clean',
                r'dirty',
                r'pure',
                r'raw',
                r'polished',
                r'refined',
                r'crude',
                r'sophisticated',
                r'simple',
                r'complex',
                r'easy',
                r'difficult',
                r'accessible',
                r'challenging',
                r'experimental',
                r'traditional',
                r'modern',
                r'classic',
                r'contemporary',
                r'vintage',
                r'retro',
                r'nostalgic',
                r'futuristic',
                r'timeless',
                r'dated',
                r'fresh',
                r'stale',
                r'new',
                r'old',
                r'young',
                r'mature',
                r'immature',
                r'serious',
                r'playful',
                r'fun',
                r'boring',
                r'interesting',
                r'exciting',
                r'dull',
                r'vibrant',
                r'colorful',
                r'bland',
                r'spicy',
                r'sweet',
                r'bitter',
                r'sour',
                r'salty',
                r'clinical',
                # Musical instruments
                r'guitar',
                r'guitars',
                r'bass',
                r'bass guitar',
                r'drums',
                r'drummer',
                r'piano',
                r'keyboard',
                r'keyboards',
                r'synthesizer',
                r'synth',
                r'synths',
                r'violin',
                r'viola',
                r'cello',
                r'double bass',
                r'upright bass',
                r'trumpet',
                r'trombone',
                r'saxophone',
                r'sax',
                r'clarinet',
                r'flute',
                r'oboe',
                r'bassoon',
                r'french horn',
                r'horn',
                r'tuba',
                r'harmonica',
                r'accordion',
                r'banjo',
                r'mandolin',
                r'ukulele',
                r'harp',
                r'organ',
                r'electric guitar',
                r'acoustic guitar',
                r'electric bass',
                r'acoustic bass',
                r'electric piano',
                r'acoustic piano',
                r'grand piano',
                r'upright piano',
                r'drum kit',
                r'drum set',
                r'percussion',
                r'vocals',
                r'voice',
                r'singing',
                r'singer',
                r'vocalist',
                r'lead vocals',
                r'backing vocals',
                r'brass',
                r'woodwinds',
                r'wind instruments',
                r'string instruments',
                r'brass instruments',
                r'woodwind instruments',
                r'percussion instruments',
                r'electronic instruments',
                r'acoustic instruments',
                r'amplified',
                r'digital',
                r'analog',
                r'analogue',
                r'texas',
                r'houston',
                r'aoty',
                r'rem',
            ]
            
            for tag in tags:
                tag_name = tag.item.name.lower()
                # Skip if tag matches any of the skip patterns
                if any(re.search(pattern, tag_name) for pattern in skip_patterns):
                    continue
                # Skip if tag is purely numeric
                if tag_name.isdigit():
                    continue
                # Skip if tag is empty or just whitespace
                if not tag_name.strip():
                    continue
                # Skip if tag contains the artist's name
                if artist.lower() in tag_name or tag_name in artist.lower():
                    continue
                # Apply title case to the tag
                filtered_tags.append(title_case_tag(tag_name))
            
            # For Last.fm, treat all as styles (no specific genre classification)
            return set(), set(filtered_tags)
        except Exception as e:
            logger.warning(f"Error fetching Last.fm tags for {artist} - {album}: {e}")
            return set(), set()

    def get_spotify_genres(self, artist: str, album: str) -> tuple[Set[str], Set[str]]:
        """Get genres from Spotify for an album. Returns (genres, styles)."""
        try:
            # Skip artist fallback for generic artist names
            generic_artists = {'various artists', 'various', 'compilation', 'soundtrack', 'va', 'unknown artist', 'unknown'}
            
            # Search for the album first
            results = self.spotify.search(
                q=f"album:{album} artist:{artist}",
                type="album",
                limit=1
            )
            
            artist_id = None
            
            if results['albums']['items']:
                # Found the album, get artist from album data
                album_id = results['albums']['items'][0]['id']
                album_data = self.spotify.album(album_id)
                artist_id = album_data['artists'][0]['id']
            else:
                # No album found, try searching for just the artist (unless it's a generic artist)
                if artist.lower() in generic_artists:
                    logger.info(f"Skipping artist search for generic artist: {artist}")
                    return set(), set()
                
                logger.info(f"Album not found on Spotify, searching for artist: {artist}")
                artist_results = self.spotify.search(
                    q=f"artist:{artist}",
                    type="artist",
                    limit=1
                )
                
                if artist_results['artists']['items']:
                    artist_id = artist_results['artists']['items'][0]['id']
                else:
                    logger.warning(f"Artist {artist} not found on Spotify")
                    return set(), set()
            
            # Get artist genres
            artist_data = self.spotify.artist(artist_id)
            
            # Apply title case to genres - treat Spotify genres as genres
            spotify_genres = {title_case_tag(genre) for genre in artist_data['genres']}
            return spotify_genres, set()
        except Exception as e:
            logger.warning(f"Error fetching Spotify genres for {artist} - {album}: {e}")
            return set(), set()

    def update_plex_metadata(self, album, new_genres: Set[str], new_styles: Set[str], new_moods: Set[str]):
        """Update album metadata in Plex by appending to existing genres, styles, and moods using addGenre, addStyle, and addMood."""
        try:
            # Get existing genres
            existing_genres = set()
            if album.genres:
                existing_genres.update(g.tag for g in album.genres)
            
            # Get existing styles
            existing_styles = set()
            if album.styles:
                existing_styles.update(s.tag for s in album.styles)
            
            # Get existing moods
            existing_moods = set()
            if album.moods:
                existing_moods.update(m.tag for m in album.moods)
            
            # Determine which new genres to add
            genres_to_add = sorted(new_genres - existing_genres)
            
            # Determine which new styles to add
            styles_to_add = sorted(new_styles - existing_styles)
            
            # Determine which new moods to add
            moods_to_add = sorted(new_moods - existing_moods)
            
            if genres_to_add:
                album.addGenre(genres_to_add, locked=True)
                logger.info(f"Added {len(genres_to_add)} new genres to {album.title}")
            else:
                logger.info(f"No new genres to add for {album.title}")
            
            if styles_to_add:
                album.addStyle(styles_to_add, locked=True)
                logger.info(f"Added {len(styles_to_add)} new styles to {album.title}")
            else:
                logger.info(f"No new styles to add for {album.title}")
            
            if moods_to_add:
                album.addMood(moods_to_add, locked=True)
                logger.info(f"Added {len(moods_to_add)} new moods to {album.title}")
            else:
                logger.info(f"No new moods to add for {album.title}")
        except Exception as e:
            logger.error(f"Error updating Plex metadata for {album.title}: {e}")

    def get_plex_albums(self) -> List[Dict]:
        """Fetch albums from Plex."""
        try:
            music_library = self.plex.library.section('Music')
            albums = music_library.albums()
            
            # Apply limit if configured
            if hasattr(config, 'MAX_ALBUMS') and config.MAX_ALBUMS is not None:
                albums = albums[:config.MAX_ALBUMS]
                logger.info(f"Limited to first {config.MAX_ALBUMS} albums")
            
            logger.info(f"Found {len(albums)} albums in Plex")
            return [{'title': album.title, 'artist': album.parentTitle} for album in albums]
        except Exception as e:
            logger.error(f"Error fetching Plex albums: {e}")
            return []

    def export_no_data_albums(self):
        """Export albums with no data found to a CSV file."""
        if self.albums_no_data:
            df = pd.DataFrame(self.albums_no_data)
            filename = f"albums_no_data_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
            df.to_csv(filename, index=False)
            logger.info(f"Exported {len(self.albums_no_data)} albums with no data to {filename}")
        else:
            logger.info("No albums without data found")

    def process_albums(self):
        """Main processing function."""
        albums = self.get_plex_albums()
        logger.info(f"Processing {len(albums)} albums")

        for album_info in albums:
            try:
                logger.info(f"\n{'='*50}")
                logger.info(f"Processing: {album_info['artist']} - {album_info['title']}")
                
                # Get the Plex album object using both artist and title
                music_library = self.plex.library.section('Music')
                try:
                    # First try to find the artist
                    artist = music_library.get(album_info['artist'])
                    if artist:
                        # Then find the album within that artist's albums
                        artist_albums = artist.albums()
                    
                        
                        plex_album = next((album for album in artist_albums if album.title == album_info['title']), None)
                        if not plex_album:
                            logger.warning(f"Could not find album '{album_info['title']}' for artist '{album_info['artist']}'")
                            logger.warning(f"Available albums: {[album.title for album in artist_albums]}")
                            self.albums_no_data.append({
                                'artist': album_info['artist'],
                                'album': album_info['title'],
                                'reason': 'Album not found in Plex'
                            })
                            continue
                    else:
                        logger.warning(f"Could not find artist '{album_info['artist']}'")
                        # Try to find similar artist names
                        all_artists = music_library.search(libtype='artist')
                        similar_artists = [a.title for a in all_artists if album_info['artist'].lower() in a.title.lower() or a.title.lower() in album_info['artist'].lower()]
                        if similar_artists:
                            logger.warning(f"Similar artists found: {similar_artists}")
                        self.albums_no_data.append({
                            'artist': album_info['artist'],
                            'album': album_info['title'],
                            'reason': 'Artist not found in Plex'
                        })
                        continue
                except Exception as e:
                    logger.warning(f"Error finding album in Plex: {e}")
                    self.albums_no_data.append({
                        'artist': album_info['artist'],
                        'album': album_info['title'],
                        'reason': f'Plex lookup error: {e}'
                    })
                    continue
                
                # # Log existing Plex metadata
                # logger.info("\nExisting Plex metadata:")
                # logger.info(f"Genres: {plex_album.genres}")
                # logger.info(f"Moods: {plex_album.moods}")
                # logger.info(f"Styles: {plex_album.styles}")
                
                # Get tags from all services
                lastfm_genres, lastfm_styles = self.get_lastfm_tags(album_info['artist'], album_info['title'])
                spotify_genres, spotify_styles = self.get_spotify_genres(album_info['artist'], album_info['title'])
                
                # Get Pitchfork data
                pitchfork_data = self.get_pitchfork_data(album_info['artist'], album_info['title'])
                pitchfork_genres = set()
                pitchfork_styles = set()
                
                if pitchfork_data:
                    # Add Pitchfork genre as styles
                    if pd.notna(pitchfork_data['genre']):
                        # Split comma-separated genres and add each as a separate tag
                        genres = [genre.strip() for genre in str(pitchfork_data['genre']).split(',')]
                        for genre in genres:
                            if genre:  # Only add non-empty genres
                                pitchfork_styles.add(title_case_tag(genre))
                    
                    # Add rating tag if score exists
                    if pd.notna(pitchfork_data['score']):
                        score = float(pitchfork_data['score'])
                        if score == 10.0:
                            pitchfork_styles.add("Pitchfork 10")
                        elif score >= 9.0:
                            pitchfork_styles.add("Pitchfork 9+")
                        elif score >= 8.0:
                            pitchfork_styles.add("Pitchfork 8+")
                        elif score >= 7.0:
                            pitchfork_styles.add("Pitchfork 7+")
                    
                    # Add BNM tag if applicable
                    if pd.notna(pitchfork_data['bnm']) and pitchfork_data['bnm']:
                        pitchfork_styles.add("Best New Music")
                
                # Get RYM data
                rym_data = self.get_rym_data(album_info['artist'], album_info['title'])
                rym_genres = set()
                rym_styles = set()
                rym_moods = set()
                
                if rym_data:
                    # Add primary genres as genres
                    if pd.notna(rym_data['primary_genres']) and rym_data['primary_genres']:
                        genres = [genre.strip() for genre in str(rym_data['primary_genres']).split(',')]
                        for genre in genres:
                            if genre:  # Only add non-empty genres
                                rym_genres.add(title_case_tag(genre))
                    
                    # Add secondary genres as styles
                    if pd.notna(rym_data['secondary_genres']) and rym_data['secondary_genres']:
                        # Skip if the value is "NA"
                        if str(rym_data['secondary_genres']).upper() != 'NA':
                            genres = [genre.strip() for genre in str(rym_data['secondary_genres']).split(',')]
                            for genre in genres:
                                if genre and genre.upper() != 'NA':  # Only add non-empty genres and skip "NA"
                                    rym_styles.add(title_case_tag(genre))
                    
                    # Add descriptors as moods
                    if pd.notna(rym_data['descriptors']) and rym_data['descriptors']:
                        descriptors = [descriptor.strip() for descriptor in str(rym_data['descriptors']).split(',')]
                        for descriptor in descriptors:
                            if descriptor:  # Only add non-empty descriptors
                                # Handle special cases for vocals
                                if descriptor.lower() == 'malevocals':
                                    rym_moods.add("Male Vocals")
                                elif descriptor.lower() == 'femalevocals':
                                    rym_moods.add("Female Vocals")
                                elif descriptor.lower() == 'androgynousvocals':
                                    rym_moods.add("Androgynous Vocals")
                                else:
                                    rym_moods.add(title_case_tag(descriptor))
                    
                    # Add rating tag if average rating is high enough
                    if pd.notna(rym_data['avg_rating']):
                        rating = float(rym_data['avg_rating'])
                        if rating >= 4.0:
                            rym_styles.add(f"RYM Average Rating: 4+")
                        elif rating >= 3.8:
                            rym_styles.add(f"RYM Average Rating: 3.8+")
                
                # Check Rolling Stone Top 500
                rolling_stone_styles = set()
                if self.get_rolling_stone_data(album_info['artist'], album_info['title']):
                    rolling_stone_styles.add("Rolling Stone Top 500")
                
                # Check if we found any external data
                has_external_data = bool(
                    lastfm_styles or spotify_genres or pitchfork_styles or 
                    rym_genres or rym_styles or rym_moods or rolling_stone_styles
                )
                
                if not has_external_data:
                    logger.info(f"No external data found for {album_info['artist']} - {album_info['title']}")
                    self.albums_no_data.append({
                        'artist': album_info['artist'],
                        'album': album_info['title'],
                        'reason': 'No external data found'
                    })
                
                # Combine all genres, styles, and moods
                all_genres = lastfm_genres.union(spotify_genres).union(pitchfork_genres).union(rym_genres)
                all_styles = lastfm_styles.union(spotify_styles).union(pitchfork_styles).union(rym_styles).union(rolling_stone_styles)
                all_moods = rym_moods  # Only RYM provides moods for now
                
                # If no RYM data, classify other tags based on existing Plex genres
                if not rym_data:
                    # Combine all tags from other sources
                    other_tags = lastfm_styles.union(spotify_genres).union(pitchfork_styles)
                    classified_genres, classified_styles = self.classify_tags_as_genres_or_styles(other_tags)
                    
                    # Update the final sets
                    all_genres = all_genres.union(classified_genres)
                    all_styles = classified_styles  # Replace with classified styles
                
                # Apply RYM hierarchical expansion to all genres and styles
                logger.info(f"Before hierarchical expansion - Genres: {len(all_genres)}, Styles: {len(all_styles)}")
                
                # Expand genres hierarchically
                expanded_genres = self.rym_hierarchy.expand_genres_hierarchically(list(all_genres))
                
                # Expand styles hierarchically  
                expanded_styles = self.rym_hierarchy.expand_genres_hierarchically(list(all_styles))
                
                # Update the sets with expanded versions
                all_genres = expanded_genres
                all_styles = expanded_styles
                
                logger.info(f"After hierarchical expansion - Genres: {len(all_genres)}, Styles: {len(all_styles)}")
                
                # Deduplicate: remove any genres from styles to avoid duplication
                all_styles = all_styles - all_genres
                
                logger.info(f"New combined genres: {all_genres}")
                logger.info(f"New combined styles: {all_styles}")
                logger.info(f"New combined moods: {all_moods}")
                
                # Show what's new
                existing_genres = set()
                existing_styles = set()
                existing_moods = set()
                if plex_album.genres:
                    existing_genres.update(g.tag for g in plex_album.genres)
                if plex_album.moods:
                    existing_moods.update(m.tag for m in plex_album.moods)
                if plex_album.styles:
                    existing_styles.update(s.tag for s in plex_album.styles)
                
                new_genres = all_genres - existing_genres
                new_styles = all_styles - existing_styles
                new_moods = all_moods - existing_moods
                
                logger.info(f"New genres: {new_genres}")
                logger.info(f"New styles: {new_styles}")
                logger.info(f"New moods: {new_moods}")
                
                # Be nice to the APIs
                sleep_time = getattr(config, 'SLEEP_BETWEEN_REQUESTS', 1)
                time.sleep(sleep_time)
                
                # Update Plex metadata
                self.update_plex_metadata(plex_album, new_genres, new_styles, new_moods)
                
            except Exception as e:
                logger.error(f"Error processing album {album_info['title']}: {e}")
                self.albums_no_data.append({
                    'artist': album_info['artist'],
                    'album': album_info['title'],
                    'reason': f'Processing error: {e}'
                })
                continue

        # Export albums with no data found
        self.export_no_data_albums()

    def classify_tags_as_genres_or_styles(self, tags: Set[str]) -> tuple[Set[str], Set[str]]:
        """Classify tags as genres or styles based on existing Plex genres."""
        genres = set()
        styles = set()
        
        for tag in tags:
            # Check if tag matches an existing Plex genre (case-insensitive)
            if tag.lower() in self.existing_plex_genres:
                genres.add(tag)
            else:
                styles.add(tag)
        
        return genres, styles

def main():
    updater = MusicMetadataUpdater()
    updater.process_albums()

if __name__ == "__main__":
    main() 