# Docker Setup for Hue Event Logger

## Quick Start

1. **Copy the environment file and configure it:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set your Hue bridge IP address:
   ```
   HUE_BRIDGE_IP=192.168.1.100
   ```

2. **Build and run with Docker Compose:**
   ```bash
   docker-compose up -d
   ```

3. **Check the logs:**
   ```bash
   docker-compose logs -f huelog
   ```

4. **Access the application:**
   Open http://localhost:9090 in your browser

## Docker Commands

### Build the image manually:
```bash
docker build -t hue-event-logger .
```

### Run the container manually:
```bash
docker run -d \
  --name hue-event-logger \
  -p 9090:8080 \
  -e HUE_BRIDGE_IP=192.168.1.100 \
  hue-event-logger
```

### Stop and remove:
```bash
docker-compose down
```

### View logs:
```bash
docker-compose logs huelog
```

### Restart the service:
```bash
docker-compose restart huelog
```

## Configuration

The Docker setup uses environment variables for configuration. Key variables:

- `HUE_BRIDGE_IP`: Your Hue bridge IP address (required)
- `HUE_APP_KEY`: Application key (auto-generated if not provided)
- `HUE_VERIFY_TLS`: Whether to verify TLS certificates (default: false)
- `FLASK_DEBUG`: Enable debug mode (default: false)

## Data Persistence

- **Database**: Stored in a Docker-managed volume named `hue-data`
- **Logs**: Available via `docker-compose logs` command

### Accessing the Database File

If you need direct access to the SQLite database file, you can:

1. **Copy the database from the container:**
   ```bash
   docker cp hue-event-logger:/app/data/hue_events.sqlite ./hue_events.sqlite
   ```

2. **Alternative: Use bind mount** (if you prefer local file access):
   ```bash
   # Create local data directory
   mkdir -p data
   
   # Modify docker-compose.yml to use bind mount instead:
   # Replace "- hue-data:/app/data" with "- ./data:/app/data"
   ```

## Health Check

The container includes a health check that verifies the application is responding on port 8080.

## Troubleshooting

1. **Can't connect to Hue bridge**: Ensure your bridge IP is correct and the container can reach your network
2. **Permission issues**: The container uses Docker-managed volumes to avoid permission conflicts
3. **Database access**: Use `docker cp` command to copy the database file if needed locally
