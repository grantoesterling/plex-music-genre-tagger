# Create Plex Smart Collections Script

This script automatically creates Plex Smart Collections based on rules defined in JSON configuration files. It's designed to work with music libraries and supports filtering by genres, moods, styles, and other metadata attributes.

## Features

- **JSON Configuration**: Define collections using simple JSON files
- **Flexible Filtering**: Support for genres, moods, styles, artists, albums, years, and more
- **Dry Run Mode**: Preview what collections would be created without actually creating them
- **Existing Collection Handling**: Optionally update existing collections or skip them
- **Comprehensive Logging**: Detailed output showing what's happening during execution
- **Error Handling**: Robust error handling with informative messages

## Prerequisites

1. **Plex Server**: A running Plex Media Server with a music library
2. **Configuration**: A properly configured `config.py` file (copy from `config.py.example`)
3. **Dependencies**: All required Python packages (automatically installed via `requirements.txt`)

## Installation

The script uses the existing project dependencies. If you haven't already, install them:

```bash
pip install -r requirements.txt
```

## Configuration

### Plex Configuration

Make sure your `config.py` file includes the necessary Plex settings:

```python
# Plex Server Configuration
PLEX_URL = 'https://your-plex-server:32400'
PLEX_TOKEN = 'your-plex-token'
MUSIC_LIBRARY_NAME = 'Music'  # Name of your music library
```

### JSON Collection Configuration

Create JSON files defining your smart collections. The format is an array of collection objects:

```json
[
  {
    "title": "Collection Name",
    "summary": "Optional description of the collection",
    "sort": "random",
    "filters": {
      "genre": ["Genre1", "Genre2"],
      "mood": ["mood1", "mood2"],
      "style": ["style1", "style2"]
    }
  }
]
```

#### Supported Filter Types

| Filter Type | Description | Example Values |
|-------------|-------------|----------------|
| `genre` | Music genres | `["Jazz", "Electronic", "Classical"]` |
| `mood` | Music moods | `["chill", "energetic", "dark"]` |
| `style` | Music styles | `["bebop", "ambient", "progressive"]` |
| `artist` | Artist names | `["Miles Davis", "Brian Eno"]` |
| `album` | Album titles | `["Kind of Blue", "Ambient 1"]` |
| `year` | Release year | `["2020", "2021"]` or `"2020"` |
| `decade` | Release decade | `["1970s", "1980s"]` |
| `rating` | User rating | `["8", "9", "10"]` |

#### Sort Options

You can specify how the collection should be sorted using the `sort` field. If not specified, collections will be sorted randomly by default for better music discovery.

| Sort Option | Description |
|------------|-------------|
| `random` | Random order (default - great for discovery!) |
| `titleSort` | Alphabetical by album title |
| `artist.titleSort` | Alphabetical by artist name |
| `year` | By release year |
| `addedAt` | By date added to library |
| `lastViewedAt` | By last played date |
| `userRating` | By user rating |

#### Example Configuration Files

**Basic Example** (`data/smart_collections_lisbon.json`):
```json
[
  {
    "title": "Terminal Rituals",
    "sort": "random",
    "filters": {
      "genre": ["Ambient", "Berlin School", "Minimalism"],
      "mood": ["ritualistic", "hypnotic", "calm", "futuristic"]
    }
  }
]
```

**Advanced Example** (`data/smart_collections_examples.json`):
```json
[
  {
    "title": "Dark Jazz Vibes",
    "summary": "Moody and atmospheric jazz perfect for late night listening",
    "sort": "random",
    "filters": {
      "genre": ["Jazz"],
      "mood": ["dark", "brooding", "melancholic", "atmospheric"]
    }
  },
  {
    "title": "Modern Classical",
    "summary": "Contemporary classical compositions and neo-classical works",
    "sort": "titleSort",
    "filters": {
      "genre": ["Classical", "Neo-Classical", "Contemporary Classical"],
      "mood": ["contemplative", "serene", "dramatic"]
    }
  }
]
```

## Usage

### Basic Usage

```bash
# Use the default configuration file (data/smart_collections_lisbon.json)
python create_smart_collections.py

# Use a custom configuration file
python create_smart_collections.py data/my_collections.json

# Use a different configuration file
python create_smart_collections.py data/smart_collections_examples.json
```

### Dry Run Mode

Preview what collections would be created without actually creating them:

```bash
# Dry run with default config
python create_smart_collections.py --dry-run

# Dry run with custom config
python create_smart_collections.py data/my_collections.json --dry-run
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `config_file` | Path to JSON configuration file (default: `data/smart_collections_lisbon.json`) |
| `--dry-run` | Show what would be created without actually creating collections |
| `--help`, `-h` | Show help message and exit |

### Examples

```bash
# Create collections from default config
python create_smart_collections.py

# Create collections from custom config
python create_smart_collections.py data/my_collections.json

# Preview what would be created
python create_smart_collections.py --dry-run

# Preview custom config
python create_smart_collections.py data/my_collections.json --dry-run

# Show help
python create_smart_collections.py --help
```

## How It Works

1. **Load Configuration**: The script reads the JSON configuration file
2. **Connect to Plex**: Establishes connection to your Plex server
3. **Process Collections**: For each collection in the configuration:
   - Checks if a collection with the same name already exists
   - Builds PlexAPI-compatible filters from the configuration
   - Creates the smart collection with the specified filters
   - Optionally adds a summary description
4. **Provide Summary**: Shows how many collections were created successfully

## Existing Collections

When a collection with the same name already exists, the script will:

1. **In Interactive Mode**: Ask if you want to update the existing collection
2. **In Dry Run Mode**: Show that the collection exists but won't modify it

If you choose to update an existing collection, the script will:
1. Delete the existing collection
2. Create a new collection with the updated filters

## Error Handling

The script includes comprehensive error handling for common issues:

- **Missing Configuration**: Clear error if `config.py` is not found
- **Invalid JSON**: Helpful error messages for JSON parsing issues
- **Plex Connection Issues**: Detailed error information for connection problems
- **Collection Creation Errors**: Specific error messages for individual collection failures

## Tips and Best Practices

### Filter Matching

- Filter values must match exactly what's in your Plex library
- Use the exact spelling and capitalization as they appear in Plex
- Check your library's existing genres and moods to ensure proper matching

### Testing

- Always use `--dry-run` first to preview changes
- Start with simple collections to test your configuration
- Check the Plex web interface to verify collections were created correctly

### Performance

- The script processes collections sequentially
- Large libraries may take some time to process
- Consider creating smaller, more specific collections for better performance

### Maintenance

- Keep your JSON configuration files in version control
- Document the purpose of each collection in the `summary` field
- Regularly review and update collections as your library grows

## Troubleshooting

### Common Issues

**"No valid filters found"**
- Check that your filter values match exactly what's in Plex
- Verify the filter types are supported (see table above)
- Ensure your JSON syntax is correct

**"Collection already exists"**
- Choose to update the existing collection when prompted
- Or use a different collection name in your configuration

**Plex connection errors**
- Verify your `PLEX_URL` and `PLEX_TOKEN` in `config.py`
- Ensure your Plex server is running and accessible
- Check that the `MUSIC_LIBRARY_NAME` matches your library name exactly

### Debug Mode

For more detailed output, you can modify the logging level in the script or run Python with verbose output:

```bash
python -v create_smart_collections.py
```

## Configuration File Examples

The repository includes several example configuration files:

- `data/smart_collections_lisbon.json` - Default configuration with one collection
- `data/smart_collections_examples.json` - Multiple example collections showing different filter types

Feel free to use these as templates for your own collections! 