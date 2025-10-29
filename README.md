# Hue Event Logger

A comprehensive Philips Hue bridge event monitoring application that captures and analyzes device events in real-time. The system provides IoT device event processing, health diagnostics tracking, and a web dashboard for monitoring smart home device connectivity and performance.

## Features

- 🔄 **Real-time Event Stream**: Captures live events from Philips Hue bridge via Server-Sent Events (SSE)
- 📊 **Device Health Monitoring**: Tracks disconnections, downtime, battery status, and device age
- 🌐 **Web Dashboard**: Interactive interface for viewing events and device health metrics
- 📱 **Live Event Tail**: Real-time event streaming in the web interface
- 🔍 **Event Filtering**: Search and filter events by device, type, or content
- 📈 **Health Scoring**: Algorithmic health scoring based on device behavior patterns
- 🐳 **Docker Support**: Easy deployment with Docker and Docker Compose
- 💾 **SQLite Database**: Persistent storage for events, devices, and diagnostics

## Quick Start

### Docker (Recommended)

1. **Set up environment variables:**
   ```bash
   cp .env.example .env
   ```

2. **Start the application:**
   ```bash
   docker-compose up -d
   ```

3. **Access the web interface:**
   Open http://localhost:9090 in your browser

### Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   ```

3. **Run the application:**
   ```bash
   python app.py
   ```

4. **Access the web interface:**
   Open http://localhost:8080 in your browser

## Initial Setup & Authentication

When you first run the application without a stored app key:

1. **Start the application** - it will detect no existing authentication
2. **Press the physical button** on your Hue bridge when prompted
3. **The app will automatically authenticate** and store the credentials
4. **Event monitoring begins** immediately after successful authentication

## Web Interface

### Event Log (`/`)
- View all captured events in chronological order
- Filter events by device ID, type, or JSON content
- Adjustable event limit (default: 200, max: 10,000)
- Real-time updates when used with the tail endpoint

### Health Dashboard (`/health`)
- Device health overview with scoring algorithm
- Track disconnections, downtime, and battery status
- Configurable time range (default: last 7 days)
- Sort by health score to identify problematic devices

### Live Event Tail (`/tail`)
- Real-time Server-Sent Events stream
- Low-latency event updates
- JSON format for easy integration

## API Endpoints

### Statistics
```http
GET /api/stats
```
Returns basic system statistics including event counts, device counts, and recent activity.

### Device Refresh
```http
GET /api/refresh-devices
```
Manually refresh the device catalog from the Hue bridge.

### Connectivity Information
```http
GET /resource/zigbee_connectivity
GET /resource/zgp_connectivity
```
Get detailed Zigbee and Zigbee Green Power connectivity information.

## Configuration

Configuration is managed through environment variables:

### Required
- `HUE_BRIDGE_IP`: IP address of your Philips Hue bridge

### Optional
- `HUE_APP_KEY`: Application key (auto-generated if not provided)
- `HUE_VERIFY_TLS`: Verify TLS certificates (default: false)
- `DB_PATH`: SQLite database path (default: ./hue_events.sqlite)
- `FLASK_HOST`: Flask server host (default: 0.0.0.0)
- `FLASK_PORT`: Flask server port (default: 8080)
- `FLASK_DEBUG`: Enable debug mode (default: false)

### Advanced Settings
- `EVENT_QUEUE_SIZE`: Max events in live queue (default: 10000)
- `AUTH_TIMEOUT`: Seconds to wait for button press (default: 30)
- `STREAM_TIMEOUT`: Stream connection timeout (default: 60)
- `RECONNECT_DELAY`: Delay between reconnection attempts (default: 2)

## Health Scoring Algorithm

The system calculates device health scores using the following formula:

```
Health Score = (3 × disconnects) + (2 × (downtime_minutes ÷ 10)) + (2 × age_flag) + (2 × battery_low)
```

Where:
- `disconnects`: Number of disconnect events
- `downtime_minutes`: Total minutes device was unreachable
- `age_flag`: 1 if device hasn't been seen for >1 hour, 0 otherwise  
- `battery_low`: 1 if battery is low, 0 otherwise

Higher scores indicate less healthy devices.

## Database Schema

### Events Table
- Raw event data with timestamp, resource ID, type, and full JSON payload
- Primary key: auto-incrementing ID
- Indexed by timestamp and resource ID

### Devices Table  
- Device catalog with names, types, and metadata
- Upserted from bridge API and event data
- Primary key: resource ID

### Diagnostics Table
- Daily aggregated health metrics per device
- Tracks disconnects, downtime, battery status
- Primary key: (resource_id, day)

## Architecture

### Core Components

- **Event Stream Processor** (`hue_processor.py`): Handles real-time SSE from Hue bridge
- **Database Layer** (`database.py`): SQLite operations with connection management  
- **Web Application** (`app.py`): Flask server with dashboard and API endpoints
- **Authentication** (`hue_auth.py`): Manages Hue bridge pairing workflow
- **Configuration** (`config.py`): Pydantic-based config with environment loading

### Data Flow

1. **Events stream** from Hue bridge via HTTPS SSE → `HueEventProcessor`
2. **Raw events** stored in `events` table + processed for diagnostics in `diag` table
3. **Live events** queued in memory for `/tail` SSE endpoint  
4. **Web dashboard** queries aggregated health data with scoring algorithm

## Development

### Project Structure
```
├── app.py              # Flask web application
├── config.py           # Configuration management  
├── database.py         # SQLite database operations
├── hue_auth.py         # Hue bridge authentication
├── hue_processor.py    # Event stream processing
├── requirements.txt    # Python dependencies
├── Dockerfile         # Container build configuration
├── docker-compose.yml # Multi-container orchestration
└── templates/         # HTML templates
    ├── index.html     # Event log interface
    └── health.html    # Health dashboard
```

### Adding New Event Types

1. Extend `_update_device_diagnostics()` in `hue_processor.py`
2. Add database schema changes to `init_db()` in `database.py`  
3. Update health scoring in `/health` route if needed

### Database Schema Changes

- Add DDL to `init_db()` method with `IF NOT EXISTS` guards
- Consider SQLite compatibility for the current implementation
- Update cleanup methods for new tables if needed

## Monitoring & Debugging

### View Live Events
```bash
curl -N http://localhost:8080/tail
```

### Check Container Logs
```bash
docker-compose logs -f huelog
```

### Database Access
```bash
# Copy database from container
docker cp hue-event-logger:/app/data/hue_events.sqlite ./local.sqlite

# Or use sqlite3 directly
sqlite3 ./local.sqlite "SELECT * FROM events LIMIT 10;"
```

### Health Check
```bash
curl http://localhost:8080/api/stats
```

## Troubleshooting

### Common Issues

1. **Can't connect to Hue bridge**
   - Verify bridge IP address is correct
   - Ensure bridge is on same network/accessible
   - Check firewall settings

2. **Authentication fails**  
   - Press physical button on bridge when prompted
   - Ensure bridge supports API v2 (newer bridges)
   - Check bridge firmware version

3. **Events not appearing**
   - Verify app key is valid with `/api/stats`
   - Check event processor logs for connection issues
   - Test with `/api/refresh-devices` to verify connectivity

4. **Performance issues**
   - Check database size and consider cleanup
   - Adjust event queue size if memory usage is high  
   - Monitor disk space for SQLite database

### Log Analysis

The application uses structured logging with colored console output. Key log levels:

- **INFO**: Normal operational messages
- **WARNING**: Non-critical issues (e.g., connection retries)  
- **ERROR**: Serious issues requiring attention
- **DEBUG**: Detailed troubleshooting information (when debug mode enabled)

## Requirements

- Python 3.11+
- Philips Hue Bridge (API v2 compatible)
- Network connectivity between application and bridge
- For Docker: Docker and Docker Compose

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with appropriate tests
4. Submit a pull request

## Support

- Check the logs for error messages and debugging information
- Review the troubleshooting section above
- For Hue bridge API questions, consult Philips developer documentation
- For application-specific issues, check existing GitHub issues

---

**Note**: This application is designed for monitoring and diagnostics. It does not control Hue devices - it only observes their state changes and connectivity.