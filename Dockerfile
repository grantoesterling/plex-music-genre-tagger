FROM python:3.9-slim

# Install required system packages
RUN apt-get update && apt-get install -y \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py ./
COPY data/ ./data/
COPY config.py ./

# Create log directory
RUN mkdir -p /var/log/plex-updater

# Create cron job
RUN echo "0 2 * * * cd /app && python3 clean_plex_metadata.py >> /var/log/plex-updater/clean_metadata.log 2>&1" > /etc/cron.d/clean-metadata
RUN echo "0 3 * * * cd /app && python3 rym_plex_updater.py >> /var/log/plex-updater/rym_update.log 2>&1" > /etc/cron.d/rym-update

# Give execution rights on the cron job
RUN chmod 0644 /etc/cron.d/clean-metadata
RUN chmod 0644 /etc/cron.d/rym-update

# Apply cron job
RUN crontab /etc/cron.d/clean-metadata
RUN crontab /etc/cron.d/rym-update

# Create the log file to be able to run tail
RUN touch /var/log/plex-updater/clean_metadata.log
RUN touch /var/log/plex-updater/rym_update.log

# Run cron in foreground
CMD ["cron", "-f"] 