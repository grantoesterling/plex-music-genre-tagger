#!/usr/bin/env python3
"""
RYM Genre Hierarchy Utility

Parses the RYM genre tree structure and provides functionality for hierarchical tagging.
When a genre is applied, all its parent genres are also applied.
"""

import json
import os
from typing import Dict, List, Set, Tuple

class RYMGenreHierarchy:
    """Handles RYM genre hierarchy and hierarchical tagging."""
    
    def __init__(self, genre_tree_file: str = "./data/rym-genre-tree.json", excluded_genres_file: str = "./data/excluded-meta-genres.json"):
        """Initialize with genre tree file and excluded genres file."""
        self.genre_tree_file = genre_tree_file
        self.excluded_genres_file = excluded_genres_file
        self.genre_to_parents = {}  # genre_name -> set of all parent paths
        self.all_genres = set()     # all valid genre names
        self.excluded_genres = set()  # meta-genres to exclude from tagging
        self.load_excluded_genres()
        self.load_hierarchy()
    
    def load_excluded_genres(self):
        """Load excluded meta-genres from configuration file."""
        if not os.path.exists(self.excluded_genres_file):
            # Create default excluded genres file
            default_excluded = {
                "excluded_meta_genres": [
                    "Regional Music",
                ],
                "description": "Meta-genres that are too broad to be useful as tags. These will be excluded from hierarchical expansion."
            }
            
            try:
                with open(self.excluded_genres_file, 'w', encoding='utf-8') as f:
                    json.dump(default_excluded, f, indent=2)
                print(f"📝 Created default excluded genres file: {self.excluded_genres_file}")
                print(f"   Edit this file to customize which meta-genres to exclude")
            except Exception as e:
                print(f"⚠️  Could not create excluded genres file: {e}")
        
        try:
            with open(self.excluded_genres_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.excluded_genres = set(data.get('excluded_meta_genres', []))
            print(f"📋 Loaded {len(self.excluded_genres)} excluded meta-genres")
            print(f"   Excluded: {', '.join(sorted(self.excluded_genres))}")
            
        except Exception as e:
            print(f"⚠️  Error loading excluded genres: {e}")
            self.excluded_genres = set()
    
    def load_hierarchy(self):
        """Load and parse the genre hierarchy."""
        if not os.path.exists(self.genre_tree_file):
            print(f"⚠️  Genre tree file not found: {self.genre_tree_file}")
            return
        
        try:
            with open(self.genre_tree_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Parse the hierarchy
            self._parse_tree(data['genreHierarchy'])
            
            print(f"✅ Loaded RYM genre hierarchy: {len(self.all_genres)} genres")
            print(f"   Genres with multiple parents: {sum(1 for g in self.genre_to_parents.values() if len(g) > 1)}")
            
        except Exception as e:
            print(f"❌ Error loading genre hierarchy: {e}")
    
    def _parse_tree(self, nodes: List[Dict], parent_path: List[str] = None):
        """Recursively parse the genre tree."""
        if parent_path is None:
            parent_path = []
        
        for node in nodes:
            genre_name = node['name']
            current_path = parent_path + [genre_name]
            
            # Add this genre to our registry
            self.all_genres.add(genre_name)
            
            # Store the parent path for this genre
            if genre_name not in self.genre_to_parents:
                self.genre_to_parents[genre_name] = set()
            
            # Add all ancestors in this path as parents
            for i in range(len(parent_path)):
                ancestor_path = tuple(parent_path[:i+1])
                self.genre_to_parents[genre_name].add(ancestor_path)
            
            # Recursively process children
            if 'children' in node and node['children']:
                self._parse_tree(node['children'], current_path)
    
    def get_all_parent_genres(self, genre_name: str) -> Set[str]:
        """Get all parent genres for a given genre."""
        if genre_name not in self.genre_to_parents:
            return set()
        
        parents = set()
        for path in self.genre_to_parents[genre_name]:
            parents.update(path)
        
        return parents
    
    def expand_genres_hierarchically(self, genres: List[str]) -> Set[str]:
        """
        Expand a list of genres to include all their parents, excluding meta-genres.
        
        Args:
            genres: List of genre names
            
        Returns:
            Set of all genres including hierarchical parents (minus excluded meta-genres)
        """
        expanded = set()
        
        for genre in genres:
            if genre in self.all_genres:
                # Add the genre itself (unless it's excluded)
                if genre not in self.excluded_genres:
                    expanded.add(genre)
                
                # Add all its parents (excluding meta-genres)
                parents = self.get_all_parent_genres(genre)
                for parent in parents:
                    if parent not in self.excluded_genres:
                        expanded.add(parent)
            else:
                # Genre not in hierarchy, add as-is (for backwards compatibility)
                # But still check if it's in excluded list
                if genre not in self.excluded_genres:
                    expanded.add(genre)
        
        return expanded
    
    def is_valid_genre(self, genre_name: str) -> bool:
        """Check if a genre name is valid in the RYM hierarchy."""
        return genre_name in self.all_genres
    
    def is_excluded_genre(self, genre_name: str) -> bool:
        """Check if a genre is excluded from tagging."""
        return genre_name in self.excluded_genres
    
    def filter_valid_genres(self, genres: List[str]) -> Tuple[List[str], List[str]]:
        """
        Filter genres into valid and invalid lists.
        
        Returns:
            Tuple of (valid_genres, invalid_genres)
        """
        valid = []
        invalid = []
        
        for genre in genres:
            if self.is_valid_genre(genre):
                valid.append(genre)
            else:
                invalid.append(genre)
        
        return valid, invalid
    
    def filter_excluded_genres(self, genres: List[str]) -> Tuple[List[str], List[str]]:
        """
        Filter genres into included and excluded lists.
        
        Returns:
            Tuple of (included_genres, excluded_genres)
        """
        included = []
        excluded = []
        
        for genre in genres:
            if self.is_excluded_genre(genre):
                excluded.append(genre)
            else:
                included.append(genre)
        
        return included, excluded
    
    def get_genre_paths(self, genre_name: str) -> List[List[str]]:
        """Get all hierarchical paths for a genre."""
        if genre_name not in self.genre_to_parents:
            return []
        
        paths = []
        for path_tuple in self.genre_to_parents[genre_name]:
            path = list(path_tuple) + [genre_name]
            paths.append(path)
        
        return paths
    
    def print_genre_info(self, genre_name: str):
        """Print detailed information about a genre."""
        if not self.is_valid_genre(genre_name):
            print(f"❌ '{genre_name}' is not a valid RYM genre")
            return
        
        print(f"🎵 Genre: {genre_name}")
        
        if self.is_excluded_genre(genre_name):
            print(f"   ⚠️  This is an excluded meta-genre (will not be tagged)")
        
        paths = self.get_genre_paths(genre_name)
        if paths:
            print(f"   Hierarchical paths:")
            for i, path in enumerate(paths, 1):
                path_str = " → ".join(path)
                print(f"   {i}. {path_str}")
        
        parents = self.get_all_parent_genres(genre_name)
        if parents:
            # Show which parents would be excluded
            included_parents = [p for p in parents if p not in self.excluded_genres]
            excluded_parents = [p for p in parents if p in self.excluded_genres]
            
            if included_parents:
                print(f"   Parent genres (will be tagged): {', '.join(sorted(included_parents))}")
            if excluded_parents:
                print(f"   Parent genres (excluded): {', '.join(sorted(excluded_parents))}")
        else:
            print(f"   No parent genres (top-level)")


def test_hierarchy():
    """Test the hierarchy functionality."""
    hierarchy = RYMGenreHierarchy()
    
    # Test the Black Ambient example
    print("\n🧪 Testing Black Ambient:")
    hierarchy.print_genre_info("Black Ambient")
    
    expanded = hierarchy.expand_genres_hierarchically(["Black Ambient"])
    print(f"\n   Expanded genres (excluding meta-genres): {', '.join(sorted(expanded))}")
    
    # Test a few more examples
    test_genres = ["Aggrotech", "Delta Blues", "Gagaku"]
    
    for genre in test_genres:
        print(f"\n🧪 Testing {genre}:")
        hierarchy.print_genre_info(genre)


if __name__ == "__main__":
    test_hierarchy() 