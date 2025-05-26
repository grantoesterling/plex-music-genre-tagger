# Plex Music Metadata Updater

A Python script that automatically enriches your Plex music library with metadata from multiple sources including Last.fm, Spotify, Pitchfork, RateYourMusic (RYM), and Rolling Stone.

## Features

- **Multi-source metadata aggregation**: Combines data from 5 different music databases
- **Intelligent classification**: Automatically categorizes tags as genres, styles, or moods
- **Fuzzy matching**: Finds albums even with slight name variations
- **Fallback artist search**: Gets artist data when specific albums aren't found
- **Smart filtering**: Removes unwanted tags (years, countries, subjective opinions, etc.)
- **Proper capitalization**: Applies consistent title case formatting
- **Non-destructive updates**: Appends to existing metadata without overwriting
- **Comprehensive logging**: Tracks processing and exports albums with no data found

## Data Sources

### Primary Sources
- **Last.fm**: Album and artist tags → Styles
- **Spotify**: Artist genres → Genres
- **RateYourMusic (RYM)**: Primary genres → Genres, Secondary genres → Styles, Descriptors → Moods
- **Pitchfork**: Reviews and ratings → Styles (includes "Best New Music" and rating tiers)
- **Rolling Stone**: Top 500 albums → "Rolling Stone Top 500" style tag

### Metadata Classification
- **Genres**: Spotify artist genres + RYM primary genres
- **Styles**: Last.fm tags + Pitchfork data + RYM secondary genres + rating tags
- **Moods**: RYM descriptors (with special handling for vocal types)

## Prerequisites

- Python 3.7+
- Plex Media Server with music library
- API keys for Last.fm and Spotify
- CSV data files (see Data Files section)

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/plex-music-updater.git
   cd plex-music-updater
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up configuration**:
   ```bash
   cp config.py.example config.py
   ```
   Edit `config.py` with your actual API keys and Plex server details.

5. **Download data files** (see Data Files section below)

## Configuration

### API Keys Required

1. **Plex Token**: Follow [Plex's guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) to find your token
2. **Last.fm API**: Create an account at [Last.fm API](https://www.last.fm/api/account/create)
3. **Spotify API**: Create an app at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/applications)

### Plex Setup
- Ensure your Plex server is accessible
- The script connects to your music library section named "Music"
- SSL verification is disabled for local Plex connections

## Data Files

The script requires several CSV data files that are not included in the repository due to size:

### Required Files
- `pitchfork.csv` - Pitchfork album reviews and ratings
- `rym.csv` - RateYourMusic top 5000 albums with genres and descriptors  
- `rolling-stone.csv` - Rolling Stone's top 500 albums

### Expected CSV Formats

**pitchfork.csv**:
```csv
artist,album,genre,score,bnm
Artist Name,Album Name,Genre Name,8.5,true
```

**rym.csv**:
```csv
artist_name,release_name,primary_genres,secondary_genres,descriptors,avg_rating
Artist Name,Album Name,"Rock, Alternative Rock","Indie Rock, Post-Rock","atmospheric, melancholic",3.85
```

**rolling-stone.csv**:
```csv
Artist,Album Name
Artist Name,Album Name
```

## Usage

### Basic Usage
```bash
python plex_music_updater.py
```

### Configuration Options
Edit `config.py` to customize:
- `MAX_ALBUMS`: Limit processing to X albums (useful for testing)
- `SLEEP_BETWEEN_REQUESTS`: Adjust API request delays

### Output
- Processes all albums in your Plex music library
- Logs detailed information about each album processed
- Exports `albums_no_data_TIMESTAMP.csv` with albums that couldn't be matched
- Updates Plex with new genres, styles, and moods

## Tag Filtering

The script includes extensive filtering to remove unwanted tags:
- Years and decades (e.g., "2010", "2010s")
- Countries and nationalities (e.g., "american", "british")
- Subjective opinions (e.g., "amazing", "overrated")
- Personal collection tags (e.g., "favorites", "owned")
- Technical terms (e.g., "vinyl", "remaster")
- Instruments (when not genre-relevant)

## Special Handling

### Vocal Types
RYM descriptors are converted to proper mood tags:
- `malevocals` → "Male Vocals"
- `femalevocals` → "Female Vocals"  
- `androgynousvocals` → "Androgynous Vocals"

### Capitalization
Smart title case with special rules:
- Handles hyphens: `alt-country` → "Alt-Country"
- Preserves acronyms: `uk` → "UK"
- Special corrections: `hip-hop` → "Hip Hop"

### Generic Artists
Skips artist fallback search for compilation albums with generic names like "Various Artists"

## Troubleshooting

### Common Issues
1. **SSL Certificate errors**: The script disables SSL verification for local Plex connections
2. **Rate limiting**: Adjust `SLEEP_BETWEEN_REQUESTS` if you encounter API limits
3. **Album not found**: Check the exported CSV for albums that couldn't be matched

### Logging
The script provides detailed logging including:
- Albums processed successfully
- API lookup results
- Fuzzy matching scores
- New metadata added

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- **Last.fm** for comprehensive music tagging
- **Spotify** for artist genre classification
- **Pitchfork** for music criticism and ratings
- **RateYourMusic** for detailed genre taxonomy
- **Rolling Stone** for canonical album rankings
- **Plex** for the excellent media server platform

## Disclaimer

This tool is for personal use with your own Plex library. Respect the terms of service of all APIs used. The script includes rate limiting and respectful API usage patterns. 