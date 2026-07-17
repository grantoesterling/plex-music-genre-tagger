"""RYM Genres Plugin for Beets

This plugin fetches genre data from Rate Your Music (RYM) scraped data
stored in Firebase and applies it to music releases during import.
Writes descriptors to Descriptors, genres to Genres, secondary genres to SecondaryGenres,
and parent genres to Groupings.
"""

import json
import urllib.request
import urllib.parse
import os
import time
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime
from beets.plugins import BeetsPlugin
from beets import ui
from beets.autotag import AlbumInfo, TrackInfo
from beets.autotag.hooks import Distance
import mediafile

# Import mutagen for direct FLAC array writing
try:
    from mutagen.flac import FLAC
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

# Import the genre hierarchy handler
try:
    from .rym_genre_hierarchy import RYMGenreHierarchy
except ImportError:
    # Fallback if hierarchy module isn't available
    RYMGenreHierarchy = None


def similarity(a, b):
    """Calculate similarity between two strings with Unicode normalization."""
    # Normalize Unicode to handle different representations of the same characters
    a_norm = unicodedata.normalize('NFKC', a.lower())
    b_norm = unicodedata.normalize('NFKC', b.lower())
    return SequenceMatcher(None, a_norm, b_norm).ratio()


class RYMGenresPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        
        # Get the directory containing this plugin file
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(os.path.dirname(plugin_dir), 'data')
        
        self.config.add({
            'firebase_url': '',  # Users must configure this themselves
            'similarity_threshold': 0.8,
            'max_genres': 10,
            'max_secondary_genres': 20,
            'max_descriptors': 60,
            'max_groupings': 30,  # Limit for parent genres
            'auto_tag': True,
            'use_hierarchy': True,  # Enable hierarchical parent genre tagging
            'genre_tree_file': os.path.join(data_dir, 'rym-genre-tree.json'),
            'excluded_genres_file': os.path.join(data_dir, 'excluded-meta-genres.json'),
            'cache_duration': 3600,  # Cache duration in seconds (1 hour default)
            'cache_file': os.path.join(data_dir, 'rym_genres_cache.json'),
            'require_rym_match': False,  # Fail import if no RYM match found
            'log_missing_matches': True,  # Log albums without RYM matches to file
            'missing_matches_logfile': '/config/rym_missing_matches.log',
            'flexible_artist_matching': True,  # Allow matches with very high title similarity despite low artist similarity
            'title_match_threshold': 0.95,  # Minimum title similarity for flexible matching
        })
        self.rym_data = None
        self.genre_hierarchy = None
        self.logged_albums = set()  # Track albums we've already logged to prevent duplicates
        
        # Register event listener for import task creation
        self.register_listener('import_task_created', self.on_import_task_created)
        
        # Add MediaField definitions for secondary_genre and descriptor to ensure they get written to files
        try:
            # Define secondary_genre field to be written to SECONDARY_GENRE tag in files
            secondary_genre_field = mediafile.MediaField(
                mediafile.MP3DescStorageStyle(u'Secondary Genre'),
                mediafile.ListStorageStyle(u'SECONDARY_GENRE'),
            )
            self.add_media_field('secondary_genre', secondary_genre_field)
            
            # Define descriptor field to be written to DESCRIPTORS tag in files  
            descriptor_field = mediafile.MediaField(
                mediafile.MP3DescStorageStyle(u'Descriptors'),
                mediafile.ListStorageStyle(u'DESCRIPTORS'),
            )
            self.add_media_field('descriptor', descriptor_field)
        except ValueError:
            # Fields might already exist, that's okay
            pass
        
    def commands(self):
        def _needs_flac_array_update(self, album):
            """Check if any FLAC files in the album need array formatting updates."""
            if not MUTAGEN_AVAILABLE:
                return False
                
            for item in album.items():
                path_str = item.path.decode('utf-8') if isinstance(item.path, bytes) else str(item.path)
                if not path_str.lower().endswith('.flac'):
                    continue
                    
                try:
                    flac_file = FLAC(path_str)
                    
                    # Check each tag field
                    for field, tag_name in [('genre', 'GENRE'), ('secondary_genre', 'SECONDARY_GENRE'), 
                                          ('descriptor', 'DESCRIPTORS'), ('grouping', 'GROUPING')]:
                        if hasattr(item, field):
                            item_value = getattr(item, field)
                            if item_value and isinstance(item_value, str) and ';' in item_value:
                                # Item has semicolon-separated string
                                file_values = flac_file.get(tag_name, [])
                                if len(file_values) == 1 and ';' in file_values[0]:
                                    # File has single string with semicolons instead of array
                                    return True
                                    
                except Exception:
                    # If we can't read the file, assume it needs updating
                    return True
                    
            return False

        def rym_command(lib, opts, args):
            """Command to manually fetch genres for specific albums."""
            query = ' '.join(args) if args else ''
            items = lib.albums(query) if query else lib.albums()
            
            total_processed = 0
            total_updated = 0
            total_skipped = 0
            total_missing = 0
            missing_matches = []  # Track missing matches for logging
            force_update = opts.force  # Check if --force flag is used
            
            for album in items:
                total_processed += 1
                
                # Check if RYM data exists before processing
                release_data = self._find_matching_release(album)
                if not release_data:
                    album_info = f"{album.albumartist} - {album.album}"
                    ui.print_(f"🔍 No RYM match found: {album_info}")
                    missing_matches.append(album_info)
                    total_missing += 1
                    continue
                
                # Calculate what the new tags would be
                genres = release_data.get('genres', [])
                max_genres = self.config['max_genres'].get(int)
                new_genre = '; '.join(genres[:max_genres]) if genres and max_genres > 0 else ''
                
                secondary_genres = release_data.get('secondaryGenres', [])
                max_secondary_genres = self.config['max_secondary_genres'].get(int)
                new_secondary_genre = '; '.join(secondary_genres[:max_secondary_genres]) if secondary_genres and max_secondary_genres > 0 else ''
                
                descriptors = release_data.get('descriptors', [])
                max_descriptors = self.config['max_descriptors'].get(int)
                new_descriptor = '; '.join(descriptors[:max_descriptors]) if descriptors and max_descriptors > 0 else ''
                
                # Calculate groupings (parent genres)
                groupings = self._get_parent_genres(genres)
                new_grouping = '; '.join(groupings) if groupings else ''
                
                # Check if we need to update (unless force is used)
                needs_update = force_update
                update_reason = ""
                
                if not force_update:
                    current_genre = getattr(album, 'genre', '') or ''
                    current_secondary_genre = getattr(album, 'secondary_genre', '') or ''
                    current_descriptor = getattr(album, 'descriptor', '') or ''
                    current_grouping = getattr(album, 'grouping', '') or ''
                    
                    # Check if tags are different
                    tags_different = not (current_genre == new_genre and 
                                        current_secondary_genre == new_secondary_genre and 
                                        current_descriptor == new_descriptor and 
                                        current_grouping == new_grouping)
                    
                    # Check if FLAC files need array formatting
                    flac_needs_arrays = _needs_flac_array_update(self, album)
                    
                    if tags_different:
                        needs_update = True
                        update_reason = "tags changed"
                    elif flac_needs_arrays:
                        needs_update = True
                        update_reason = "FLAC array formatting needed"
                    else:
                        update_reason = "already up-to-date"
                
                if not needs_update:
                    ui.print_(f"⏭️  Skipping ({update_reason}): {album.albumartist} - {album.album}")
                    total_skipped += 1
                    continue
                elif force_update:
                    ui.print_(f"🔄 Force updating: {album.albumartist} - {album.album}")
                else:
                    ui.print_(f"🔄 Updating ({update_reason}): {album.albumartist} - {album.album}")
                    
                # Apply tags (but suppress internal logging for command mode)
                old_log_level = self._log.level
                self._log.setLevel(40)  # Only show ERROR level during command processing
                
                self._apply_rym_tags(album)
                album.store()
                
                # Apply tags to individual tracks and write to files
                for item in album.items():
                    self._apply_rym_tags_to_item(item, album)
                    item.store()  # Save to database
                    self._write_item_with_flac_arrays(item)  # Write metadata to file with FLAC arrays
                
                # Restore original log level
                self._log.setLevel(old_log_level)
                
                total_updated += 1
                
                # Show consolidated output for command
                ui.print_(f"✅ Updated RYM tags: {album.albumartist} - {album.album}")
                
                # Show detailed tag information
                tags_info = []
                if hasattr(album, 'genre') and album.genre:
                    tags_info.append(f"📁 Genres ({len([g.strip() for g in album.genre.split(';') if g.strip()])}): {album.genre}")
                if hasattr(album, 'secondary_genre') and album.secondary_genre:
                    tags_info.append(f"🎨 Secondary Genres ({len([s.strip() for s in album.secondary_genre.split(';') if s.strip()])}): {album.secondary_genre}")
                if hasattr(album, 'descriptor') and album.descriptor:
                    descriptor_list = [d.strip() for d in album.descriptor.split(';') if d.strip()]
                    tags_info.append(f"🎭 Descriptors ({len(descriptor_list)}): {album.descriptor}")
                if hasattr(album, 'grouping') and album.grouping:
                    tags_info.append(f"🏷️  Groupings ({len([g.strip() for g in album.grouping.split(';') if g.strip()])}): {album.grouping}")
                
                for info in tags_info:
                    ui.print_(f"   {info}")
                    
                # Add spacing between albums
                ui.print_("")
                    
            # Summary
            ui.print_(f"\n📊 Summary: Updated {total_updated}/{total_processed} albums, skipped {total_skipped}, missing {total_missing}")
            if force_update and total_processed > 0:
                ui.print_(f"   🔄 Force mode: Updated all matched albums regardless of current state")
            
            # Log missing matches to file if enabled
            if missing_matches and self.config['log_missing_matches'].get(bool):
                logfile_path = self.config['missing_matches_logfile'].get()
                
                # Ensure log directory exists
                log_dir = os.path.dirname(logfile_path)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                
                try:
                    with open(logfile_path, 'a', encoding='utf-8') as f:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        for match in missing_matches:
                            f.write(f"{timestamp}: {match}\n")
                    ui.print_(f"📝 Logged {len(missing_matches)} missing matches to: {logfile_path}")
                except Exception as e:
                    ui.print_(f"⚠️  Could not write to log file {logfile_path}: {e}")
        
        rym_cmd = ui.Subcommand('rym', help='fetch RYM genres for albums')
        rym_cmd.parser.add_option('-f', '--force', action='store_true', 
                                 help='force update all matched albums regardless of current state (useful when RYM data has been updated)')
        rym_cmd.func = rym_command
        return [rym_cmd]
    
    def album_imported(self, _session, task):
        """Hook called when an album is imported."""
        if task.is_album:
            self._apply_rym_tags(task.album)
            # Store album changes to database
            task.album.store()
            
            # Apply tags to individual tracks and write to files
            for item in task.album.items():
                self._apply_rym_tags_to_item(item, task.album)
                item.store()  # Save to database
                self._write_item_with_flac_arrays(item)  # Write metadata to file with FLAC arrays
    
    def album_distance(self, items, album_info, mapping):
        """Autotagger hook to enhance album info with RYM data."""
        if not self.config['auto_tag'].get(bool):
            return Distance()
            
        # Try to find RYM data for this album
        release_data = self._find_rym_release(album_info.artist, album_info.album)
        
        if release_data:
            # Enhance album_info with RYM data
            self._enhance_album_info(album_info, release_data)
            
            # Create a unique key for this album to prevent duplicate logging
            album_key = f"{album_info.artist} - {album_info.album}"
            
            # Only log detailed info if we haven't logged this album yet
            if album_key not in self.logged_albums:
                self.logged_albums.add(album_key)
                
                # Log detailed values instead of just counts
                applied_details = []
                if hasattr(album_info, 'genre') and album_info.genre:
                    genres_list = [g.strip() for g in album_info.genre.split(';') if g.strip()]
                    applied_details.append(f"Genres: {', '.join(genres_list)}")
                if hasattr(album_info, 'secondary_genre') and album_info.secondary_genre:
                    secondary_genres_list = [s.strip() for s in album_info.secondary_genre.split(';') if s.strip()]
                    applied_details.append(f"Secondary Genres: {', '.join(secondary_genres_list)}")
                if hasattr(album_info, 'descriptor') and album_info.descriptor:
                    descriptors_list = [d.strip() for d in album_info.descriptor.split(';') if d.strip()]
                    applied_details.append(f"Descriptors: {', '.join(descriptors_list)}")
                if hasattr(album_info, 'grouping') and album_info.grouping:
                    groupings_list = [g.strip() for g in album_info.grouping.split(';') if g.strip()]
                    applied_details.append(f"Groupings: {', '.join(groupings_list)}")
                
                if applied_details:
                    self._log.info(f"🎵 RYM enhanced {album_info.artist} - {album_info.album}")
                    for detail in applied_details:
                        self._log.info(f"   {detail}")
                else:
                    self._log.warning(f"🔍 RYM matched but no data: {album_info.artist} - {album_info.album}")
            
            return Distance()  # Return empty Distance object (doesn't affect matching)
        else:
            # No RYM match found
            if self.config['require_rym_match'].get(bool):
                # This will be handled by the candidates hook instead
                pass
            else:
                self._log.debug(f"⚠️  No RYM match found: {album_info.artist} - {album_info.album}")
            
            return Distance()
    
    def _load_rym_data(self):
        """Load RYM data from Firebase or cache."""
        if self.rym_data is not None:
            return
            
        # Try to load from cache first
        if self._load_from_cache():
            return
            
        # Cache miss - fetch from Firebase
        try:
            firebase_url = self.config['firebase_url'].get()
            if not firebase_url:
                self._log.error("Firebase URL not configured. Please set 'firebase_url' in your beets config under the rym_genres section.")
                self.rym_data = {}
                return
                
            self._log.info(f"Fetching RYM data from configured Firebase URL")
            
            with urllib.request.urlopen(firebase_url) as response:
                full_data = json.loads(response.read().decode())
                
            # The data structure is already artist_key -> {album_key: album_data}
            self.rym_data = full_data
            
            # Count total albums across all artists
            total_albums = 0
            for artist_data in self.rym_data.values():
                if isinstance(artist_data, dict):
                    total_albums += len(artist_data)
            
            self._log.info(f"Loaded {len(self.rym_data)} artists with {total_albums} total albums from RYM")
            
            # Cache the data for next time
            self._save_to_cache()
                
        except Exception as e:
            self._log.error(f"Failed to load RYM data: {e}")
            self.rym_data = {}

    def _load_from_cache(self):
        """Load RYM data from cache if available and not expired."""
        try:
            cache_file = self.config['cache_file'].get()
            cache_duration = self.config['cache_duration'].get(int)
            
            if not os.path.exists(cache_file):
                return False
                
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)
                
            cached_time = cached_data.get('timestamp', 0)
            current_time = time.time()
            
            if current_time - cached_time < cache_duration:
                self.rym_data = cached_data['data']
                
                # Count albums for logging
                total_albums = 0
                for artist_data in self.rym_data.values():
                    if isinstance(artist_data, dict):
                        total_albums += len(artist_data)
                        
                age_hours = (current_time - cached_time) / 3600
                self._log.info(f"Loaded {len(self.rym_data)} artists with {total_albums} albums from cache (age: {age_hours:.1f}h)")
                return True
            else:
                self._log.info("Cache expired, will fetch fresh data from Firebase")
                return False
                
        except Exception as e:
            self._log.warning(f"Failed to load cache: {e}")
            return False

    def _save_to_cache(self):
        """Save RYM data to cache file."""
        if self.rym_data is None:
            return
            
        try:
            cache_file = self.config['cache_file'].get()
            
            # Ensure cache directory exists
            cache_dir = os.path.dirname(cache_file)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            
            cache_data = {
                'timestamp': time.time(),
                'data': self.rym_data
            }
            
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f)
                
            self._log.info(f"Cached RYM data to {cache_file}")
            
        except Exception as e:
            self._log.warning(f"Failed to save cache: {e}")

    def _find_rym_release(self, artist, album_title):
        """Find matching release in RYM data by artist and album name."""
        self._load_rym_data()
        
        if not self.rym_data:
            return None
            
        artist_lower = artist.lower()
        album_lower = album_title.lower()
        threshold = self.config['similarity_threshold'].get(float)
        
        best_match = None
        best_score = 0
        
        # Handle nested structure: artist_key -> {album_key: album_data, ...}
        for artist_data in self.rym_data.values():
            if not isinstance(artist_data, dict):
                continue
                
            # Each artist_data contains multiple albums
            for album_key, release_data in artist_data.items():
                if not isinstance(release_data, dict):
                    continue
                    
                rym_artist_raw = release_data.get('artistName', '')
                rym_title_raw = release_data.get('releaseTitle', '')
                
                if not rym_artist_raw or not rym_title_raw:
                    continue
                
                # Process RYM artist name to handle variations
                rym_artist_variations = self._get_artist_variations(rym_artist_raw)
                
                # Process album title to handle variations
                album_variations = self._get_album_variations(album_title)
                rym_title_variations = self._get_album_variations(rym_title_raw)
                
                # Calculate similarity scores for each artist variation
                best_artist_score = 0
                for rym_artist in rym_artist_variations:
                    artist_score = similarity(artist_lower, rym_artist.lower())
                    best_artist_score = max(best_artist_score, artist_score)
                
                # Calculate similarity scores for each album title variation
                best_title_score = 0
                for album_var in album_variations:
                    for rym_title_var in rym_title_variations:
                        title_score = similarity(album_var.lower(), rym_title_var.lower())
                        best_title_score = max(best_title_score, title_score)
                
                combined_score = (best_artist_score + best_title_score) / 2
                
                # Add debug logging for failed matches
                if best_title_score > 0.9 and best_artist_score < 0.3:
                    self._log.debug(f"🔍 High title match but low artist match: '{artist}' vs '{rym_artist_raw}' | '{album_title}' vs '{rym_title_raw}' (artist: {best_artist_score:.3f}, title: {best_title_score:.3f})")
                
                if combined_score > best_score and combined_score >= threshold:
                    best_score = combined_score
                    best_match = release_data
                    self._log.debug(f"🎯 RYM match candidate: {rym_artist_raw} - {rym_title_raw} (score: {combined_score:.3f})")
                elif (self.config['flexible_artist_matching'].get(bool) and 
                      best_title_score >= self.config['title_match_threshold'].get(float) and 
                      best_artist_score < threshold):
                    # Special case: Very high title match with low artist match might indicate alias/collaboration
                    self._log.info(f"🤔 Flexible matching - High title match: '{album_title}' vs '{rym_title_raw}' (title: {best_title_score:.3f}, artist: {best_artist_score:.3f})")
                    if combined_score > best_score:
                        best_score = combined_score
                        best_match = release_data
                        self._log.info(f"   📝 Using this match via flexible artist matching")
                
        if best_match:
            self._log.debug(f"🏆 Best RYM match: '{artist} - {album_title}' → {best_match.get('artistName')} - {best_match.get('releaseTitle')} (score: {best_score:.3f})")
        else:
            self._log.debug(f"❌ No RYM match above threshold {threshold:.2f} for: {artist} - {album_title}")
            # Add some additional debug info about close matches
            if best_score > 0:
                closest_artist = ""
                closest_title = ""
                for artist_data in self.rym_data.values():
                    if not isinstance(artist_data, dict):
                        continue
                    for album_key, release_data in artist_data.items():
                        if not isinstance(release_data, dict):
                            continue
                        rym_artist = release_data.get('artistName', '')
                        rym_title = release_data.get('releaseTitle', '')
                        if rym_artist and rym_title:
                            artist_sim = similarity(artist.lower(), rym_artist.lower())
                            title_sim = similarity(album_title.lower(), rym_title.lower())
                            combined = (artist_sim + title_sim) / 2
                            if combined == best_score:
                                closest_artist = rym_artist
                                closest_title = rym_title
                                break
                self._log.debug(f"   🔍 Closest match was: {closest_artist} - {closest_title} (score: {best_score:.3f})")
        
        return best_match

    def _get_artist_variations(self, artist_name):
        """Generate variations of artist name for better matching, with Unicode support."""
        import re
        
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

    def _get_album_variations(self, album_title):
        """Generate variations of album title for better matching, with Unicode support."""
        import re
        
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
        
        # Normalize punctuation (: vs ፡, etc.)
        normalized_punct = album_title
        normalized_punct = re.sub(r'፡', ':', normalized_punct)  # Ethiopian colon to regular colon
        normalized_punct = re.sub(r'\s*:\s*', ': ', normalized_punct)  # Normalize colon spacing
        normalized_punct = re.sub(r'\s+', ' ', normalized_punct).strip()  # Normalize whitespace
        if normalized_punct != album_title:
            variations.append(normalized_punct)
            # Add Unicode normalized version
            punct_norm = unicodedata.normalize('NFKC', normalized_punct)
            if punct_norm != normalized_punct:
                variations.append(punct_norm)
        
        # Remove volume/number info (e.g., "Series 14: Title" -> "Series: Title")
        volume_removed = re.sub(r'\b\d+\s*:\s*', ': ', album_title)
        if volume_removed != album_title:
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

    def _find_matching_release(self, album):
        """Find matching release in RYM data."""
        # Use artist credit if available (often matches RYM better for international artists)
        artist = getattr(album, 'albumartist_credit', None) or album.albumartist
        return self._find_rym_release(artist, album.album)
    
    def _enhance_album_info(self, album_info, release_data):
        """Enhance AlbumInfo with RYM data for autotagger."""
        if not release_data:
            return
            
        # Add genres
        genres = release_data.get('genres', [])
        max_genres = self.config['max_genres'].get(int)
        if genres and max_genres > 0:
            album_info.genre = '; '.join(genres[:max_genres])  # Store as string for consistency
        
        # Add secondary genres
        secondary_genres = release_data.get('secondaryGenres', [])
        max_secondary_genres = self.config['max_secondary_genres'].get(int)
        if secondary_genres and max_secondary_genres > 0:
            album_info.secondary_genre = '; '.join(secondary_genres[:max_secondary_genres])  # Store as string for consistency
        
        # Add descriptors
        descriptors = release_data.get('descriptors', [])
        max_descriptors = self.config['max_descriptors'].get(int)
        if descriptors and max_descriptors > 0:
            album_info.descriptor = '; '.join(descriptors[:max_descriptors])  # Store as string for consistency
            
        # Add groupings (parent genres)
        groupings = self._get_parent_genres(genres)
        if groupings:
            album_info.grouping = '; '.join(groupings)  # Store as string for consistency

    def _get_parent_genres(self, genres):
        """Get parent genres for a list of primary genres, including top-level genres with no parents."""
        if not self.config['use_hierarchy'].get(bool) or not genres:
            return []
            
        self._load_genre_hierarchy()
        if not self.genre_hierarchy:
            return []
            
        try:
            # Get all parent genres for the primary genres
            all_parents = set()
            top_level_genres = set()  # Track genres that are already top-level
            
            for genre in genres:
                parents = self.genre_hierarchy.get_all_parent_genres(genre)
                if parents:
                    # Genre has parents - add them to the parent set
                    all_parents.update(parents)
                else:
                    # Genre has no parents - it's already a top-level genre
                    top_level_genres.add(genre)
                    self._log.debug(f"   🔝 '{genre}' is a top-level genre with no parents")
            
            # Remove the original genres from parents (we don't want duplicates)
            all_parents = all_parents - set(genres)
            
            # Add top-level genres that have no parents to the groupings
            all_parents.update(top_level_genres)
            
            # Filter out excluded meta-genres from parent genres
            if hasattr(self.genre_hierarchy, 'excluded_genres'):
                all_parents = all_parents - self.genre_hierarchy.excluded_genres
                self._log.debug(f"   🚫 Filtered out excluded meta-genres from parent genres")
            
            # Sort and limit
            max_groupings = self.config['max_groupings'].get(int)
            parent_list = sorted(list(all_parents))
            
            if top_level_genres:
                self._log.debug(f"   🏷️  Added {len(top_level_genres)} top-level genres to groupings: {sorted(list(top_level_genres))}")
            
            return parent_list[:max_groupings] if max_groupings > 0 else parent_list
            
        except Exception as e:
            self._log.warning(f"Error getting parent genres: {e}")
            return []

    def _apply_rym_tags(self, album):
        """Apply RYM tags to an album (Genres, SecondaryGenres, Descriptors, Groupings)."""
        release_data = self._find_matching_release(album)
        
        if not release_data:
            self._log.debug(f"🔍 No RYM match found: {album.albumartist} - {album.album}")
            return
            
        # Apply genres
        genres = release_data.get('genres', [])
        max_genres = self.config['max_genres'].get(int)
        if genres and max_genres > 0:
            album.genre = '; '.join(genres[:max_genres])  # Store as string in database
        
        # Apply secondary genres
        secondary_genres = release_data.get('secondaryGenres', [])
        max_secondary_genres = self.config['max_secondary_genres'].get(int)
        if secondary_genres and max_secondary_genres > 0:
            album.secondary_genre = '; '.join(secondary_genres[:max_secondary_genres])  # Store as string in database
        
        # Apply descriptors
        descriptors = release_data.get('descriptors', [])
        max_descriptors = self.config['max_descriptors'].get(int)
        if descriptors and max_descriptors > 0:
            album.descriptor = '; '.join(descriptors[:max_descriptors])  # Store as string in database
            
        # Apply groupings (parent genres)
        groupings = self._get_parent_genres(genres)
        if groupings:
            album.grouping = '; '.join(groupings)  # Store as string in database
            
        if genres or secondary_genres or descriptors or groupings:
            # Compact logging - just show what was applied without details
            applied_tags = []
            if genres:
                applied_tags.append(f"{len(genres)} genres")
            if secondary_genres:
                applied_tags.append(f"{len(secondary_genres)} secondary_genres")
            if descriptors:
                applied_tags.append(f"{len(descriptors)} descriptors")
            if groupings:
                applied_tags.append(f"{len(groupings)} groupings")
            
            self._log.info(f"✅ Applied RYM data to {album.albumartist} - {album.album}: {', '.join(applied_tags)}")
        else:
            self._log.warning(f"🔍 RYM matched but no tags available: {album.albumartist} - {album.album}")

    def _apply_rym_tags_to_item(self, item, album):
        """Apply RYM tags to individual track items."""
        # Copy album-level tags to track-level, converting semicolon strings to lists for FLAC arrays
        tags_copied = []
        if hasattr(album, 'genre') and album.genre:
            item.genre = album.genre
            tags_copied.append("genre")
        if hasattr(album, 'secondary_genre') and album.secondary_genre:
            item.secondary_genre = album.secondary_genre
            tags_copied.append("secondary_genre")
        if hasattr(album, 'descriptor') and album.descriptor:
            item.descriptor = album.descriptor
            tags_copied.append("descriptor")
        if hasattr(album, 'grouping') and album.grouping:
            item.grouping = album.grouping
            tags_copied.append("grouping")
            
        if tags_copied:
            self._log.debug(f"   🎵 Track tags: {item.title} ({', '.join(tags_copied)})")

    def _write_item_with_flac_arrays(self, item):
        """Write item to file with FLAC arrays for genre-related fields."""
        try:
            # Check if this is a FLAC file and mutagen is available
            # Convert path to string if it's bytes
            path_str = item.path.decode('utf-8') if isinstance(item.path, bytes) else str(item.path)
            
            if MUTAGEN_AVAILABLE and path_str.lower().endswith('.flac'):
                # Use Mutagen directly to write proper FLAC arrays
                flac_file = FLAC(path_str)
                
                arrays_written = False
                
                # Convert semicolon-separated strings to lists and write as FLAC arrays
                for field in ['genre', 'secondary_genre', 'descriptor', 'grouping']:
                    if hasattr(item, field):
                        value = getattr(item, field)
                        if value and isinstance(value, str):
                            # Map field names to FLAC tag names
                            tag_name = {
                                'genre': 'GENRE',
                                'secondary_genre': 'SECONDARY_GENRE', 
                                'descriptor': 'DESCRIPTORS',
                                'grouping': 'GROUPING'
                            }.get(field, field.upper())
                            
                            if ';' in value:
                                # Split semicolon-separated values into array
                                list_value = [v.strip() for v in value.split(';') if v.strip()]
                                flac_file[tag_name] = list_value
                                arrays_written = True
                                self._log.debug(f"   🔄 Writing {tag_name} as FLAC array ({len(list_value)} items): {list_value}")
                            else:
                                # Single value - still write as array for consistency
                                flac_file[tag_name] = [value.strip()]
                                arrays_written = True
                                self._log.debug(f"   🔄 Writing {tag_name} as FLAC array (1 item): [{value.strip()}]")
                
                if arrays_written:
                    # Save the FLAC file with arrays
                    flac_file.save()
                    self._log.debug(f"   ✅ Successfully wrote FLAC arrays to {path_str}")
                    
                    # Don't call item.try_write() for FLAC files as it might override our arrays
                    return
                    
            # Fall back to regular MediaFile writing for non-FLAC files
            item.try_write()
                
        except Exception as e:
            self._log.warning(f"Error writing FLAC arrays for {item.path}: {e}")
            # Fall back to regular write
            item.try_write()

    def _load_genre_hierarchy(self):
        """Load the RYM genre hierarchy if available and enabled."""
        if (self.genre_hierarchy is not None or 
            not self.config['use_hierarchy'].get(bool) or 
            RYMGenreHierarchy is None):
            return
            
        try:
            genre_tree_file = self.config['genre_tree_file'].get()
            excluded_file = self.config['excluded_genres_file'].get()
            self.genre_hierarchy = RYMGenreHierarchy(genre_tree_file, excluded_file)
            self._log.info("Loaded RYM genre hierarchy for parent genre tagging")
        except Exception as e:
            self._log.warning(f"Could not load genre hierarchy: {e}")
            self.genre_hierarchy = None

    def on_import_task_created(self, session, task):
        """Event handler for import task creation."""
        self._log.info(f"🔍 on_import_task_created called for task: {task}")
        
        if not self.config['require_rym_match'].get(bool):
            self._log.debug("🔍 require_rym_match is disabled, skipping check")
            return [task]  # Return the original task
            
        if task.is_album and task.items:
            # Try to determine album artist and title from the task
            first_item = task.items[0]
            artist = getattr(first_item, 'albumartist', None) or getattr(first_item, 'artist', 'Unknown')
            album = getattr(first_item, 'album', 'Unknown')
            
            self._log.info(f"🔍 Checking RYM requirement for: {artist} - {album}")
            
            # Check if we have RYM data for this album
            release_data = self._find_rym_release(artist, album)
            
            if not release_data:
                # No RYM match found - stop this task by returning empty list
                print(f"❌ No RYM match, stopping task: {artist} - {album}")
                self._log.info(f"❌ No RYM match, stopping task: {artist} - {album}")
                return []  # Return empty list to stop the task
            else:
                self._log.info(f"✅ RYM match found, allowing import: {artist} - {album}")
                return [task]  # Return the original task
        else:
            self._log.debug(f"🔍 Task is not album or has no items: is_album={task.is_album}, items={len(task.items) if task.items else 0}")
            return [task]  # Return the original task for non-album imports

