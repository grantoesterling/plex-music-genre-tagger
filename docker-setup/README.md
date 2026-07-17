# Plex Music Metadata Updater Docker Setup

This directory contains all the necessary files to run the Plex Music Metadata Updater scripts in a Docker container.

## Directory Structure
```
docker-setup/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
├── data/          # Will contain your RYM data files
└── logs/          # Will contain the script logs
```

## Setup Instructions

1. Copy your existing files into this directory:
   ```bash
   cp ../clean_plex_metadata.py .
   cp ../rym_plex_updater.py .
   cp ../config.py .
   cp ../data/rym-descriptor-tree.json data/
   cp ../data/rym-genre-tree.json data/
   ```

2. Build and start the container:
   ```bash
   docker-compose up -d
   ```

3. Check the logs:
   ```bash
   # View all logs
   docker-compose logs -f
   
   # View specific script logs
   tail -f logs/clean_metadata.log
   tail -f logs/rym_update.log
   ```

## Schedule
- `clean_plex_metadata.py`: Runs at 2:00 AM UTC daily
- `rym_plex_updater.py`: Runs at 3:00 AM UTC daily

## Manual Execution
To run the scripts manually:
```bash
docker-compose exec plex-updater python3 clean_plex_metadata.py
docker-compose exec plex-updater python3 rym_plex_updater.py
```

## Stopping the Container
```bash
docker-compose down
```

The container will automatically restart if it crashes or if your NAS reboots. 