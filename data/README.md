# Data Files

This directory should contain the CSV data files required by the Plex Music Updater. These files are not included in the repository due to their size and licensing considerations.

## Required Files

### pitchfork.csv
Contains Pitchfork album reviews and ratings.

**Required columns:**
- `artist` - Artist name
- `album` - Album name  
- `genre` - Genre classification
- `score` - Numerical score (0-10)
- `bnm` - Boolean indicating "Best New Music" status

**Example:**
```csv
artist,album,genre,score,bnm
Radiohead,OK Computer,Alternative Rock,10.0,true
```

### rym.csv
Contains RateYourMusic album data with detailed genre classifications.

**Required columns:**
- `artist_name` - Artist name
- `release_name` - Album name
- `primary_genres` - Comma-separated primary genres
- `secondary_genres` - Comma-separated secondary genres  
- `descriptors` - Comma-separated descriptive tags
- `avg_rating` - Average user rating

**Example:**
```csv
artist_name,release_name,primary_genres,secondary_genres,descriptors,avg_rating
Radiohead,OK Computer,"Rock, Alternative Rock","Art Rock, Experimental Rock","atmospheric, melancholic, complex",4.23
```

### rolling-stone.csv
Contains Rolling Stone's top albums list.

**Required columns:**
- `Artist` - Artist name
- `Album Name` - Album name

**Example:**
```csv
Artist,Album Name
The Beatles,Sgt. Pepper's Lonely Hearts Club Band
```

## Data Sources

You'll need to obtain these CSV files from the respective sources or create them yourself. The script uses fuzzy matching to handle slight variations in artist and album names.

### Potential Sources
- **Pitchfork**: Web scraping or API access
- **RateYourMusic**: Export tools or web scraping
- **Rolling Stone**: Manual compilation from published lists

## File Placement

Place the CSV files directly in this `data/` directory:
```
data/
├── pitchfork.csv
├── rym.csv
├── rolling-stone.csv
└── README.md (this file)
```

## Notes

- Files should use UTF-8 encoding
- Comma-separated values should be properly quoted if they contain commas
- Empty values should be represented as empty strings, not "NA" or "null"
- The script includes fuzzy matching with 0.8 similarity threshold for album/artist matching 