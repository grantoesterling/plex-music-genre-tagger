#!/usr/bin/env python3
"""
Recreate a Spotify playlist in Plex.

Given a Spotify playlist URL or ID, this script:
- Fetches tracks from the Spotify playlist
- Fuzzy-matches each to a track in your Plex music library (title + artist)
- Creates or updates a Plex playlist with the same name, preserving order
- Prints a summary of any tracks that couldn't be matched in Plex

Usage:
  python spotify_to_plex_playlist.py <spotify_playlist_id_or_url> [--append] [--min-score 0.75] [--limit N] [--dry-run]

Options:
  --append         Append to an existing Plex playlist instead of overwriting it
  --min-score X    Minimum similarity score to accept a match (default: 0.75)
  --limit N        Only process first N tracks from the Spotify playlist
  --dry-run        Do everything except modify Plex (print intended actions)

Requirements:
  - config.py with PLEX_URL, PLEX_TOKEN, MUSIC_LIBRARY_NAME, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
  - Dependencies in requirements.txt: plexapi, spotipy, requests
"""

import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from difflib import SequenceMatcher

from plexapi.server import PlexServer
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials


# Try to import configuration
try:
    import config
except ImportError:
    print("Error: config.py not found! Copy config.py.example to config.py and fill credentials.")
    sys.exit(1)


# Disable SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


@dataclass
class SpotifyTrack:
    title: str
    artists: List[str]
    duration_ms: Optional[int]
    album: Optional[str]


def normalize_text(text: str) -> str:
    """Normalize text for comparison: Unicode normalize, lowercase, strip punctuation/extra spaces."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKC', text)
    text = text.lower()
    # remove accents
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    # normalize separators
    text = re.sub(r'[\u2013\u2014]', '-', text)  # en/em dashes to hyphen
    # remove punctuation except spaces and hyphen
    text = re.sub(r"[^a-z0-9\-\s]", " ", text)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def simplify_title(title: str) -> str:
    """Simplify track title by removing mix/version qualifiers and bracketed info common in Spotify titles."""
    if not title:
        return ""
    t = title
    # Remove bracketed info
    t = re.sub(r"\s*\[[^\]]*\]\s*", " ", t)
    t = re.sub(r"\s*\([^)]*\)\s*", " ", t)
    # Remove trailing qualifiers like "- Remastered", "- Radio Edit", etc. (including year-first forms like "- 2018 Remaster")
    t = re.sub(r"\s*-\s*(?:\d{4}\s+)?(?:digital\s+)?(?:\w+\s+)?(remaster(?:ed)?|remix|mix|version|radio\s+edit|edit|single\s+version|mono|stereo|demo|alternate|alt\.?|live)\b.*$",
               "",
               t,
               flags=re.IGNORECASE)
    # Also remove common qualifier words if they appear at the very end without hyphen
    t = re.sub(r"\b(remaster(?:ed)?( \d{4})?|remix|mix|version|radio\s+edit|edit|single\s+version|mono|stereo|demo|alternate|alt\.?|live)\b\s*$",
               "",
               t,
               flags=re.IGNORECASE)
    # Remove "feat." parts in title
    t = re.sub(r"\s*\b(feat\.|ft\.)\b.*$", "", t, flags=re.IGNORECASE)
    # Normalize spacing
    t = re.sub(r"\s+", " ", t).strip()
    return t


def string_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def connect_to_plex() -> Tuple[PlexServer, object]:
    """Connect to Plex and return (plex, music_library)."""
    session = requests.Session()
    session.verify = False
    plex = PlexServer(config.PLEX_URL, config.PLEX_TOKEN, session=session, timeout=60)
    music_library = plex.library.section(getattr(config, 'MUSIC_LIBRARY_NAME', 'Music'))
    return plex, music_library


def connect_to_spotify() -> spotipy.Spotify:
    creds = SpotifyClientCredentials(
        client_id=config.SPOTIFY_CLIENT_ID,
        client_secret=config.SPOTIFY_CLIENT_SECRET,
    )
    return spotipy.Spotify(client_credentials_manager=creds)


def extract_playlist_id(value: str) -> str:
    """Extract playlist ID from a Spotify URL/URI or return as-is if already an ID."""
    if value.startswith("spotify:playlist:"):
        return value.split(":")[-1]
    m = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)", value)
    if m:
        return m.group(1)
    return value


def fetch_spotify_playlist(sp: spotipy.Spotify, playlist_id_or_url: str, limit: Optional[int] = None) -> Tuple[str, List[SpotifyTrack]]:
    playlist_id = extract_playlist_id(playlist_id_or_url)
    meta = sp.playlist(playlist_id, fields="name")
    playlist_name = meta["name"]

    tracks: List[SpotifyTrack] = []
    offset = 0
    page_size = 100

    while True:
        resp = sp.playlist_items(
            playlist_id,
            limit=page_size,
            offset=offset,
            additional_types=["track"],
            fields="items(track(name,artists(name),duration_ms,album(name),is_local)),next,total"
        )
        items = resp.get("items", [])
        for item in items:
            t = item.get("track") or {}
            if not t or t.get("is_local"):
                continue
            name = t.get("name") or ""
            artists = [a.get("name") for a in (t.get("artists") or []) if a and a.get("name")]
            duration_ms = t.get("duration_ms")
            album = (t.get("album") or {}).get("name")
            tracks.append(SpotifyTrack(title=name, artists=artists, duration_ms=duration_ms, album=album))
            if limit and len(tracks) >= limit:
                return playlist_name, tracks
        if not resp.get("next"):
            break
        offset += page_size
        time.sleep(0.05)  # be nice

    return playlist_name, tracks


def find_artist_obj(music_library, artist_name: Optional[str]):
    if not artist_name:
        return None
    try:
        return music_library.get(artist_name)
    except Exception:
        pass
    # Fallback: search and pick closest artist by title similarity
    try:
        results = music_library.search(artist_name) or []
        best = None
        best_score = 0.0
        for r in results:
            try:
                if getattr(r, 'type', '') != 'artist':
                    continue
                score = string_similarity(getattr(r, 'title', '') or '', artist_name)
                if score > best_score:
                    best_score = score
                    best = r
            except Exception:
                continue
        return best
    except Exception:
        return None


def search_candidate_tracks(music_library, title: str, artists: Optional[List[str]]) -> List[object]:
    """Return candidate Plex Track objects for a given title using multiple strategies (artist-aware)."""
    candidates: List[object] = []
    simple_title = simplify_title(title)
    primary_artist = (artists or [None])[0]

    # Strategy 1: direct title
    try:
        candidates.extend(music_library.searchTracks(title=title) or [])
    except Exception:
        pass

    # Strategy 2: simplified title
    if simple_title and simple_title != title:
        try:
            candidates.extend(music_library.searchTracks(title=simple_title) or [])
        except Exception:
            pass

    # Strategy 3: artist-focused search (use artist's track list and prefilter by title)
    artist_obj = find_artist_obj(music_library, primary_artist)
    if artist_obj is not None:
        try:
            artist_tracks = artist_obj.tracks() or []
            for t in artist_tracks:
                try:
                    c_title = getattr(t, 'title', '') or ''
                    if string_similarity(simplify_title(c_title), simple_title) >= 0.6:
                        candidates.append(t)
                except Exception:
                    continue
        except Exception:
            pass

    # Strategy 4: generic search (broad)
    try:
        query = title if not primary_artist else f"{title} {primary_artist}"
        mixed = music_library.search(query) or []
        for itm in mixed:
            try:
                if getattr(itm, 'type', '') == 'track':
                    candidates.append(itm)
            except Exception:
                continue
    except Exception:
        pass

    # Deduplicate by ratingKey
    seen = set()
    unique: List[object] = []
    for c in candidates:
        key = getattr(c, 'ratingKey', None)
        if key and key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def choose_best_match(candidates: List[object], sp_track: SpotifyTrack, min_score: float) -> Optional[object]:
    """Pick best Plex candidate by combining title and artist similarity (+duration sanity check)."""
    if not candidates:
        return None

    sp_title = simplify_title(sp_track.title)
    sp_primary_artist = sp_track.artists[0] if sp_track.artists else ""

    best = None
    best_score = 0.0
    for c in candidates:
        try:
            c_title = getattr(c, 'title', '') or ''
            c_artist = getattr(c, 'grandparentTitle', '') or ''

            title_score = string_similarity(simplify_title(c_title), sp_title)
            # compare to any Spotify artist, choose best
            artist_score = 0.0
            for a in (sp_track.artists or [sp_primary_artist]):
                artist_score = max(artist_score, string_similarity(c_artist, a))

            # Heavier weight on title
            score = 0.85 * title_score + 0.15 * artist_score

            # Optional duration sanity
            c_duration = getattr(c, 'duration', None)
            if c_duration and sp_track.duration_ms:
                diff_sec = abs((c_duration - sp_track.duration_ms) / 1000.0)
                if diff_sec > 20:
                    score -= 0.05  # small penalty for big duration mismatch
                else:
                    score += 0.02  # tiny bonus when close

            if score > best_score:
                best_score = score
                best = c
        except Exception:
            continue

    # Accept strong title matches even if artist is weaker
    if best:
        best_title = getattr(best, 'title', '') or ''
        best_artist = getattr(best, 'grandparentTitle', '') or ''
        title_only = string_similarity(simplify_title(best_title), sp_title)
        artist_best = 0.0
        for a in (sp_track.artists or [sp_primary_artist]):
            artist_best = max(artist_best, string_similarity(best_artist, a))

        if best_score >= min_score:
            return best
        if title_only >= 0.96:
            return best
        if title_only >= 0.92 and artist_best >= 0.4:
            return best
    return None


def ensure_playlist(plex: PlexServer, music_library, name: str, items: List[object], append: bool, dry_run: bool) -> None:
    if not items:
        print("No matched tracks to add; skipping playlist creation.")
        return

    # Filter to valid track items only
    valid_items = [i for i in items if getattr(i, 'type', '') == 'track']
    if not valid_items:
        print("No valid track items to add; skipping.")
        return

    # Find existing playlist
    existing = None
    try:
        for pl in plex.playlists():
            if getattr(pl, 'title', '') == name and getattr(pl, 'playlistType', '') == 'audio':
                existing = pl
                break
    except Exception:
        existing = None

    if existing:
        if append:
            print(f"Appending {len(valid_items)} tracks to existing Plex playlist: {name}")
            if not dry_run:
                _add_items_chunked(existing, valid_items)
            return
        else:
            print(f"Overwriting existing Plex playlist: {name}")
            if not dry_run:
                # Prefer clearing items then adding, avoids recreate pitfalls
                try:
                    existing.removeItems(existing.items())
                except Exception as e:
                    print(f"Failed to clear items: {e}. Trying delete+recreate.")
                    try:
                        existing.delete()
                        existing = None
                    except Exception as e2:
                        print(f"Failed to delete existing playlist: {e2}")
                        return
                if existing:
                    _add_items_chunked(existing, valid_items)
                    return
                # Fallthrough to create new

    print(f"Creating Plex playlist '{name}' with {len(valid_items)} tracks")
    if dry_run:
        return
    # Robust creation: create with first item, then append remainder
    try:
        first_obj = valid_items[0]
        # Ensure first item is fully fetched for reliable URI construction
        try:
            rk = getattr(first_obj, 'ratingKey', None)
            first_full = plex.fetchItem(rk) if rk is not None else first_obj
        except Exception:
            first_full = first_obj
        pl = plex.createPlaylist(name, [first_full])
        rest = valid_items[1:]
        if rest:
            _add_items_chunked(pl, rest)
    except Exception as e:
        print(f"Failed to create playlist with items: {e}")


def _add_items_chunked(playlist_obj, items: List[object], chunk_size: int = 100) -> None:
    """Add items to a playlist in chunks to avoid server limits/timeouts."""
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i+chunk_size]
        try:
            playlist_obj.addItems(chunk)
        except Exception as e:
            print(f"Error adding items chunk {i//chunk_size + 1}: {e}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in {"--help", "-h"}:
        print(__doc__)
        return

    playlist_arg = sys.argv[1]
    append = "--append" in sys.argv
    dry_run = "--dry-run" in sys.argv

    # Defaults
    min_score = 0.75
    limit = None

    for i, arg in enumerate(sys.argv):
        if arg == "--min-score" and i + 1 < len(sys.argv):
            try:
                min_score = float(sys.argv[i + 1])
            except ValueError:
                print("Invalid --min-score value; using default 0.75")
        if arg == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                print("Invalid --limit value; ignoring")

    # Connect to services
    print("Connecting to Spotify...")
    sp = connect_to_spotify()
    print("Connecting to Plex...")
    plex, music_library = connect_to_plex()

    # Fetch Spotify playlist
    print("Fetching Spotify playlist tracks...")
    playlist_name, sp_tracks = fetch_spotify_playlist(sp, playlist_arg, limit=limit)
    print(f"Playlist: {playlist_name} | Tracks fetched: {len(sp_tracks)}")

    matched_plex_tracks: List[object] = []
    unmatched: List[SpotifyTrack] = []

    for idx, st in enumerate(sp_tracks, start=1):
        title_disp = st.title
        artist_disp = ", ".join(st.artists) if st.artists else "Unknown Artist"
        print(f"[{idx}/{len(sp_tracks)}] Matching: {artist_disp} - {title_disp}")

        try:
            candidates = search_candidate_tracks(music_library, st.title, st.artists)
            match = choose_best_match(candidates, st, min_score)
        except Exception as e:
            print(f"  Error during search/match: {e}")
            match = None

        if match:
            m_artist = getattr(match, 'grandparentTitle', '')
            m_title = getattr(match, 'title', '')
            print(f"  ✓ Matched Plex: {m_artist} - {m_title}")
            matched_plex_tracks.append(match)
        else:
            print("  ✗ Not found in Plex")
            unmatched.append(st)

        # Gentle pacing to avoid hammering Plex server
        time.sleep(0.02)

    # Create/Update Plex playlist
    ensure_playlist(plex, music_library, playlist_name, matched_plex_tracks, append=append, dry_run=dry_run)

    # Report unmatched
    if unmatched:
        print("\nUnmatched tracks (not found in Plex):")
        for st in unmatched:
            a = ", ".join(st.artists) if st.artists else "Unknown Artist"
            print(f"  - {a} - {st.title}")
    else:
        print("\nAll tracks matched!")

    print(f"\nSummary: Matched {len(matched_plex_tracks)}/{len(sp_tracks)} tracks.")


if __name__ == "__main__":
    main()






