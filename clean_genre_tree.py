#!/usr/bin/env python3
"""
Script to clean up the RYM genre tree by removing unnecessary fields
while maintaining the hierarchical structure.
"""

import json
import sys
from pathlib import Path


def clean_node(node):
    """Recursively clean a node by removing unnecessary fields."""
    cleaned = {"name": node["name"]}
    
    # Only add children if they exist and are not empty
    if "children" in node and node["children"]:
        cleaned["children"] = [clean_node(child) for child in node["children"]]
    
    return cleaned


def main():
    # Input and output file paths
    input_file = Path('data/rym-genre-tree.json')
    output_file = Path('data/rym-genre-tree-clean.json')
    
    if not input_file.exists():
        print(f"Error: Input file {input_file} not found")
        sys.exit(1)
    
    try:
        # Load the genre tree
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Clean the hierarchy
        cleaned_hierarchy = []
        if 'genreHierarchy' in data:
            for top_level_node in data['genreHierarchy']:
                cleaned_hierarchy.append(clean_node(top_level_node))
        
        # Count total genres recursively
        def count_genres(nodes):
            count = 0
            for node in nodes:
                count += 1  # Count this node
                if 'children' in node:
                    count += count_genres(node['children'])  # Count children recursively
            return count
        
        total_genres = count_genres(cleaned_hierarchy)
        
        # Create cleaned output
        output_data = {
            "genreHierarchy": cleaned_hierarchy,
            "metadata": {
                "totalGenres": total_genres,
                "originalTotalGenres": data.get('totalGenres', 'unknown'),
                "sourceFile": str(input_file),
                "extractedAt": data.get('scrapedAt', 'unknown'),
                "cleanedAt": data.get('scrapedAt', 'unknown'),  # Use same timestamp for consistency
                "sourceUrl": data.get('url', 'unknown')
            }
        }
        
        # Write to output file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Cleaned genre tree with {total_genres} genres")
        print(f"📁 Output saved to: {output_file}")
        print(f"📊 Original total genres: {data.get('totalGenres', 'unknown')}")
        print(f"🧹 Removed fields: level")
        print(f"🌳 Preserved hierarchical structure")
        
        # Also output just the hierarchy if requested
        if len(sys.argv) > 1 and sys.argv[1] == '--hierarchy-only':
            hierarchy_file = Path('data/rym-genre-hierarchy-only.json')
            with open(hierarchy_file, 'w', encoding='utf-8') as f:
                json.dump(cleaned_hierarchy, f, indent=2, ensure_ascii=False)
            print(f"📁 Hierarchy-only version saved to: {hierarchy_file}")
    
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {input_file}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 