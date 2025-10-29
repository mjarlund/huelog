# Copilot Instructions for Hue Event Logger

## Project Overview
A Flask-based monitoring application that captures and analyzes Philips Hue bridge events in real-time. The system processes IoT device events, tracks device health diagnostics, and provides a web dashboard for monitoring smart home device connectivity and performance.

## Architecture & Key Components

### Core Services
- **Event Stream Processing** (`hue_processor.py`): Handles real-time SSE stream from Hue bridge, processes device events, and manages connection state tracking
- **Database Layer** (`database.py`): SQLite-based storage with three main tables: events (raw data), devices (catalog), and diag (health metrics)
- **Web Dashboard** (`app.py`): Flask application serving event logs, device health dashboard, and real-time tail functionality
- **Authentication** (`hue_auth.py`): Manages Hue bridge pairing process with interactive button press workflow

### Data Flow Pattern
1. Events stream from Hue bridge via HTTPS SSE → `HueEventProcessor`
2. Raw events stored in `events` table + processed for diagnostics in `diag` table  
3. Live events queued in memory for `/tail` SSE endpoint
4. Web dashboard queries aggregated health data with scoring algorithm

### Configuration System
Uses Pydantic models with environment variable loading via `config.py`. Key pattern: all config loaded at startup with validation, accessible via global `config` instance.

## Development Patterns

### Database Operations
- Always use `get_connection()` context manager for SQLite connections
- Upsert pattern: `INSERT ... ON CONFLICT DO UPDATE` for device catalog updates
- Health scoring algorithm: `3×disconnects + 2×(downtime_minutes/10) + 2×age_flag + 2×battery_low`

### Event Processing
```python
# Standard pattern for processing Hue bridge events
for event in events:
    for data in event.get("data", []):
        rid = data.get("id")  # Resource ID is primary key
        # Store raw event
        self.db.insert_event(now_iso, rid, dtype, data)
        # Update diagnostics 
        self._update_device_diagnostics(rid, data, now_iso, today)
```

### Error Handling
- Structured logging with `structlog` throughout
- Graceful degradation: web server starts even if Hue connection fails
- Reconnection logic with exponential backoff in event processor

## Docker & Deployment

### Container Structure
- Multi-stage potential: Currently single-stage Python 3.11-slim
- Database persistence via Docker volumes: `hue-data:/app/data`
- Health checks on Flask `/health` endpoint
- Non-root user (`appuser`) for security

### Environment Variables
```bash
# Required
HUE_BRIDGE_IP=192.168.1.100

# Auto-generated on first run
HUE_APP_KEY=

# Optional configuration  
HUE_VERIFY_TLS=false
FLASK_DEBUG=false
DB_PATH=/app/data/hue_events.sqlite
```

## Common Tasks

### Adding New Event Types
1. Extend `_update_device_diagnostics()` in `hue_processor.py`
2. Add database schema changes to `init_db()` 
3. Update health scoring in `/health` route if needed

### Database Schema Changes
- Add DDL to `init_db()` method with `IF NOT EXISTS` guards
- Consider both SQLite and potential PostgreSQL compatibility
- Update cleanup methods for new tables if needed

### Frontend Modifications
- Templates in `templates/` use vanilla JS with Jinja2
- Real-time updates via SSE (`/tail` endpoint)
- Health dashboard uses client-side filtering and sorting

## Integration Points
- **Hue Bridge API**: CLIP v2 REST API + SSE event stream
- **Authentication Flow**: Interactive pairing requires physical button press
- **Data Export**: SQLite database accessible via Docker volumes
- **Monitoring**: Health checks, structured logs, and stats API endpoints

## Testing & Debugging
```bash
# View live events
curl -N http://localhost:9090/tail

# Check container logs  
docker-compose logs -f huelog

# Database access
docker cp hue-event-logger:/app/data/hue_events.sqlite ./local.sqlite
```