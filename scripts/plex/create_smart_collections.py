#!/usr/bin/env python3
"""
Create Plex Smart Collections Script

Creates Plex Smart Collections based on rules defined in JSON configuration files.
Supports filtering by genres, moods, and other metadata attributes.

Usage:
    python create_smart_collections.py [config_file]
    
Examples:
    # Use default config file (data/smart_collections_lisbon.json)
    python create_smart_collections.py
    
    # Use custom config file
    python create_smart_collections.py data/my_collections.json
"""

import ssl
import urllib3
import json
import os
import sys
import logging
from datetime import datetime
from plexapi.server import PlexServer
from plexapi.collection import Collection
from typing import Dict, List, Any, Optional

# Disable SSL warnings and verification
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

# Import configuration
try:
    from config import PLEX_URL, PLEX_TOKEN, MUSIC_LIBRARY_NAME
except ImportError:
    print("❌ Error: config.py not found!")
    print("Please copy config.py.example to config.py and fill in your details.")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress verbose logging from external libraries
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

# Default configuration file path
DEFAULT_CONFIG_FILE = "data/smart_collections_lisbon.json"


def connect_to_plex():
    """Connect to Plex server and get music library."""
    try:
        print(f"🔌 Connecting to Plex server at {PLEX_URL}...")
        
        # Create session with SSL verification disabled
        import requests
        session = requests.Session()
        session.verify = False
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


def load_collections_config(config_file: str) -> Optional[List[Dict[str, Any]]]:
    """Load smart collections configuration from JSON file."""
    try:
        print(f"📄 Loading collections configuration from: {config_file}")
        
        if not os.path.exists(config_file):
            print(f"❌ Configuration file not found: {config_file}")
            return None
        
        with open(config_file, 'r', encoding='utf-8') as f:
            collections_config = json.load(f)
        
        if not isinstance(collections_config, list):
            print("❌ Configuration file must contain an array of collection objects")
            return None
        
        print(f"✅ Loaded {len(collections_config)} collection(s) from configuration")
        return collections_config
        
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing JSON configuration: {e}")
        return None
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        return None


def build_smart_collection_filters(collection_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build PlexAPI-compatible filters from collection configuration.
    
    Args:
        collection_config: Collection configuration dictionary
        
    Returns:
        Dictionary of filters for PlexAPI smart collection creation
    """
    filters = {}
    collection_filters = collection_config.get('filters', {})
    
    # Map configuration filter names to PlexAPI filter names
    filter_mapping = {
        'genre': 'genre',
        'mood': 'mood',
        'style': 'style',
        'year': 'year',
        'decade': 'decade',
        'artist': 'artist.title',
        'album': 'album.title',
        'track': 'track.title',
        'rating': 'userRating'
    }
    
    for config_key, plex_key in filter_mapping.items():
        if config_key in collection_filters:
            filter_value = collection_filters[config_key]
            
            # Handle both single values and lists
            if isinstance(filter_value, list):
                # For lists, PlexAPI expects comma-separated string
                filters[plex_key] = filter_value
            else:
                filters[plex_key] = [filter_value]
    
    return filters


def collection_exists(music_library, collection_name: str) -> Optional[Collection]:
    """Check if a collection with the given name already exists."""
    try:
        collections = music_library.collections()
        for collection in collections:
            if collection.title == collection_name:
                return collection
        return None
    except Exception as e:
        print(f"⚠️  Error checking existing collections: {e}")
        return None


def create_smart_collection(plex, music_library, collection_config: Dict[str, Any], dry_run: bool = False) -> bool:
    """
    Create a smart collection based on the configuration.
    
    Args:
        plex: PlexServer instance
        music_library: Music library section
        collection_config: Collection configuration dictionary
        dry_run: If True, only show what would be created without actually creating
        
    Returns:
        True if successful, False otherwise
    """
    collection_name = collection_config.get('title', 'Unnamed Collection')
    
    try:
        print(f"\n🎵 Processing collection: {collection_name}")
        
        # Check if collection already exists
        existing_collection = collection_exists(music_library, collection_name)
        if existing_collection:
            print(f"   ℹ️  Collection '{collection_name}' already exists")
            if not dry_run:
                update_choice = input(f"   ❓ Update existing collection '{collection_name}'? (y/N): ").lower().strip()
                if update_choice != 'y':
                    print(f"   ⏭️  Skipping collection '{collection_name}'")
                    return True
                
                # Delete existing collection to recreate with new filters
                print(f"   🗑️  Deleting existing collection to recreate...")
                existing_collection.delete()
        
        # Build filters for smart collection
        filters = build_smart_collection_filters(collection_config)
        
        if not filters:
            print(f"   ⚠️  No valid filters found for collection '{collection_name}'")
            return False
        
        print(f"   📋 Filters: {filters}")
        
        if dry_run:
            print(f"   🔍 DRY RUN - Would create smart collection '{collection_name}' with filters: {filters}")
            return True
        
        # Create the smart collection
        print(f"   ✨ Creating smart collection...")
        
        # Determine sort order (default to random for discovery)
        sort_order = collection_config.get('sort', 'random')
        
        # Use PlexAPI to create smart collection
        collection = Collection.create(
            server=plex,
            title=collection_name,
            section=music_library,
            smart=True,
            libtype='album',  # For music libraries, we typically want albums
            sort=sort_order,  # Default to random for better discovery
            filters=filters
        )
        
        print(f"   ✅ Successfully created smart collection '{collection_name}'")
        
        # Add optional summary if provided
        summary = collection_config.get('summary')
        if summary:
            collection.edit(summary=summary)
            print(f"   📝 Added summary to collection")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error creating collection '{collection_name}': {e}")
        return False


def main():
    """Main function."""
    
    # Parse command line arguments
    config_file = DEFAULT_CONFIG_FILE
    dry_run = False
    
    if "--help" in sys.argv or "-h" in sys.argv:
        print("🎵 Create Plex Smart Collections Script")
        print("=" * 50)
        print("Creates Plex Smart Collections based on rules defined in JSON files.")
        print()
        print("Usage:")
        print("  python create_smart_collections.py [config_file] [options]")
        print()
        print("Arguments:")
        print("  config_file      Path to JSON configuration file")
        print(f"                   (default: {DEFAULT_CONFIG_FILE})")
        print()
        print("Options:")
        print("  --dry-run        Show what would be created without actually creating")
        print("  --help, -h       Show this help message")
        print()
        print("Examples:")
        print("  # Use default config file")
        print("  python create_smart_collections.py")
        print()
        print("  # Use custom config file")
        print("  python create_smart_collections.py data/my_collections.json")
        print()
        print("  # Dry run with custom config")
        print("  python create_smart_collections.py data/my_collections.json --dry-run")
        return
    
    # Parse arguments
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--dry-run":
            dry_run = True
        elif not arg.startswith("--") and i == 1:
            config_file = arg
    
    print("🎵 Create Plex Smart Collections Script")
    print("=" * 50)
    
    if dry_run:
        print("🔍 Running in DRY RUN mode - no collections will be created")
        print()
    
    # Load collections configuration
    collections_config = load_collections_config(config_file)
    if not collections_config:
        return
    
    # Connect to Plex
    plex, music_library = connect_to_plex()
    if not music_library:
        return
    
    # Process each collection
    print(f"\n🔄 Processing {len(collections_config)} collection(s)...")
    
    successful_collections = 0
    failed_collections = 0
    
    for collection_config in collections_config:
        success = create_smart_collection(plex, music_library, collection_config, dry_run)
        if success:
            successful_collections += 1
        else:
            failed_collections += 1
    
    # Summary
    print(f"\n📊 Summary:")
    print(f"   ✅ Successful: {successful_collections}")
    print(f"   ❌ Failed: {failed_collections}")
    print(f"   📋 Total: {len(collections_config)}")
    
    if dry_run:
        print(f"\n🔍 This was a dry run - no collections were actually created.")
        print(f"   Remove --dry-run to create the collections.")
    
    print(f"\n🎉 Script completed!")


if __name__ == "__main__":
    main()






