# Plex API Wrapper

A Flask-based REST API wrapper for Plex Media Server, designed to run in Docker containers. This service provides endpoints for fetching music releases and managing moods, with built-in caching for performance.

## Features

- **Music Release Management**: Fetch all music albums from your Plex library
- **Mood Management**: Add and retrieve moods for specific releases
- **Intelligent Caching**: Configurable caching system to minimize Plex API calls
- **Docker Ready**: Containerized for easy deployment on NAS or any Docker host
- **Health Monitoring**: Built-in health check endpoints
- **RESTful API**: Clean, documented REST endpoints

## Quick Start

### 1. Get Your Plex Token

You need to find your Plex authentication token. Here are a few ways:

- **Via Plex Web**: Go to a media item, click "Get Info", then "View XML". The token is in the URL as `X-Plex-Token=`
- **Via Terminal**: 
  ```bash
  curl -u 'your-username:your-password' -X POST 'https://plex.tv/users/sign_in.xml'
  ```

### 2. Configuration

Copy the example environment file and edit it:
```bash
cp env.example .env
```

Edit `.env` with your Plex server details:
```bash
PLEX_URL=http://your-plex-server:32400
PLEX_TOKEN=your-actual-plex-token
MUSIC_LIBRARY_NAME=Music
```

### 3. Run with Docker Compose

```bash
# Build and start the service
docker-compose up -d

# Check logs
docker-compose logs -f

# Stop the service
docker-compose down
```

### 4. Alternative: Run with Docker

```bash
# Build the image
docker build -t plex-api-wrapper .

# Run the container
docker run -d \
  --name plex-api-wrapper \
  -p 5000:5000 \
  -e PLEX_URL=http://your-plex-server:32400 \
  -e PLEX_TOKEN=your-plex-token \
  plex-api-wrapper
```

## API Endpoints

### Health Check
```http
GET /health
```
Returns server status and Plex connectivity.

### Get All Music Releases
```http
GET /releases
GET /releases?refresh=true
```
Returns all music albums from your Plex library. Results are cached for 24 hours by default.

**Query Parameters:**
- `refresh=true` - Force refresh cache

**Response:**
```json
{
  "releases": [
    {
      "id": 12345,
      "title": "Album Name",
      "artist": "Artist Name",
      "year": 2023,
      "genres": ["Rock", "Alternative"],
      "moods": ["energetic", "upbeat"],
      "summary": "Album description...",
      "thumb": "/library/metadata/12345/thumb/...",
      "addedAt": "2023-01-01T12:00:00",
      "updatedAt": "2023-01-01T12:00:00"
    }
  ],
  "total_count": 150,
  "cached": true,
  "cache_timestamp": "2023-01-01T12:00:00",
  "timestamp": "2023-01-01T12:00:00"
}
```

### Add Moods to Release
```http
POST /releases/{release_id}/moods
Content-Type: application/json

{
  "moods": ["romantic", "mellow", "intimate"]
}
```

**Response:**
```json
{
  "success": true,
  "album_id": 12345,
  "album_title": "Album Name",
  "previous_moods": ["energetic"],
  "new_moods": ["energetic", "romantic", "mellow", "intimate"],
  "added_moods": ["romantic", "mellow", "intimate"],
  "timestamp": "2023-01-01T12:00:00"
}
```

### Get Release Moods
```http
GET /releases/{release_id}/moods
```

**Response:**
```json
{
  "album_id": 12345,
  "album_title": "Album Name",
  "artist": "Artist Name",
  "moods": ["energetic", "romantic", "mellow", "intimate"],
  "timestamp": "2023-01-01T12:00:00"
}
```

### Cache Management
```http
GET /cache/status     # Get cache information
POST /cache/clear     # Clear the cache
```

## Configuration

All configuration is done via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PLEX_URL` | `http://localhost:32400` | Your Plex server URL |
| `PLEX_TOKEN` | *(required)* | Your Plex authentication token |
| `MUSIC_LIBRARY_NAME` | `Music` | Name of your music library in Plex |
| `CACHE_DURATION_HOURS` | `24` | How long to cache release data |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |

## Deployment on NAS

### Synology NAS
1. Enable Docker in Package Center
2. Upload the project folder to your NAS
3. SSH into your NAS and navigate to the project folder
4. Run `docker-compose up -d`

### QNAP NAS
1. Install Container Station
2. Upload project folder
3. Use Container Station to create a new container using the docker-compose.yml

### TrueNAS
1. Enable Docker/Podman
2. Upload project folder
3. Deploy using docker-compose or create a custom app

## Development

### Local Development
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export PLEX_URL="http://your-plex-server:32400"
export PLEX_TOKEN="your-token"

# Run development server
python app.py
```

### Testing
```bash
# Test health endpoint
curl http://localhost:5000/health

# Test releases endpoint
curl http://localhost:5000/releases

# Test adding moods
curl -X POST http://localhost:5000/releases/12345/moods \
  -H "Content-Type: application/json" \
  -d '{"moods": ["romantic", "mellow"]}'
```

## Troubleshooting

### Common Issues

1. **"Failed to connect to Plex server"**
   - Check that `PLEX_URL` is correct and accessible
   - Verify your `PLEX_TOKEN` is valid
   - Ensure firewall allows access to Plex port

2. **"Music library not found"**
   - Verify `MUSIC_LIBRARY_NAME` matches your Plex library name exactly
   - Check that the library contains music content

3. **Container won't start**
   - Check Docker logs: `docker-compose logs`
   - Verify all required environment variables are set

4. **API responses are slow**
   - First request may be slow while building cache
   - Subsequent requests should be fast
   - Use `refresh=true` parameter sparingly

### Logs
```bash
# Docker Compose logs
docker-compose logs -f

# Docker logs
docker logs plex-api-wrapper -f
```

## Security

- The container runs as a non-root user
- No sensitive data is logged
- Use HTTPS in production
- Consider using Docker secrets for the Plex token

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source. Use it however you'd like! 