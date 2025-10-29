"""
Hue Event Logger - A comprehensive Philips Hue bridge event monitoring application.

This application connects to your Philips Hue bridge, captures all device events,
and provides a web interface for monitoring device health and activity.
"""
import sys
import json
import time
import datetime as dt
import structlog
import colorama
from flask import Flask, request, Response, render_template, jsonify
from contextlib import contextmanager

# Import our custom modules
from config import config
from hue_auth import HueBridgeAuth
from database import HueDatabase
from hue_processor import HueEventProcessor

# Initialize colorama for colored console output
colorama.init()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(colors=True)
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Global instances
db = None
event_processor = None


def initialize_hue_connection():
    """Initialize connection to Hue bridge with authentication."""
    global event_processor

    try:
        # Validate configuration
        logger.info("Starting Hue Event Logger",
                   bridge_ip=config.bridge_ip,
                   db_path=config.db_path,
                   verify_tls=config.verify_tls)

        # Handle authentication
        logger.info("Initializing Hue bridge authentication")
        auth = HueBridgeAuth(config.bridge_ip, config.verify_tls)
        app_key = config.app_key

        if not app_key:
            logger.info("No APP key found, starting authentication process")
            app_key = auth.generate_app_key()
            if not app_key:
                logger.error("Failed to obtain APP key")
                return False

        # Test the connection
        logger.info("Testing connection to Hue bridge")
        if not auth.test_connection(app_key):
            logger.error("Failed to connect to Hue bridge with provided key")
            return False

        # Initialize event processor
        logger.info("Initializing event processor")
        event_processor = HueEventProcessor(
            config.bridge_ip,
            app_key,
            config.verify_tls
        )

        # Start the event stream
        logger.info("Starting event stream")
        event_processor.start_event_stream()
        logger.info("Hue connection initialized successfully")
        return True

    except Exception as e:
        logger.error("Failed to initialize Hue connection", error=str(e), exc_info=True)
        return False


def create_app():
    """Create and configure the Flask application."""
    global db

    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'hue-event-logger-secret'

    # Initialize database
    db = HueDatabase()

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error("Internal server error", error=str(error))
        return jsonify({"error": "Internal server error"}), 500

    # Routes
    @app.route("/")
    def index():
        """Main events page with filtering."""
        query = request.args.get("q", "", type=str).strip()
        limit = min(request.args.get("limit", 200, type=int), 10000)  # Cap at 10k

        try:
            events = db.get_events(query, limit)
            return render_template("index.html", events=events, q=query, limit=limit)
        except Exception as e:
            logger.error("Error loading events", error=str(e))
            return render_template("index.html", events=[], q=query, limit=limit, error=str(e))

    @app.route("/health")
    def health():
        """Device health dashboard."""
        since = request.args.get("since")
        if not since:
            since = (dt.date.today() - dt.timedelta(days=7)).isoformat()

        try:
            health_data = db.get_device_health(since)
            devices = []

            now_sec = int(dt.datetime.utcnow().timestamp())

            for row in health_data:
                last_seen_ts = row["last_seen_ts"] or ""
                age_flag = 0

                if last_seen_ts:
                    try:
                        dt_obj = dt.datetime.fromisoformat(last_seen_ts.replace("Z", ""))
                        age_hours = (now_sec - int(dt_obj.timestamp())) / 3600
                        age_flag = 1 if age_hours > 1 else 0
                    except Exception:
                        age_flag = 1

                # Calculate health score
                score = (
                    3 * (row["disconnects"] or 0) +
                    2 * ((row["minutes_unreachable"] or 0) // 10) +
                    2 * age_flag +
                    2 * (row["battery_low"] or 0)
                )

                devices.append({
                    "rid": row["rid"],
                    "name": row["name"],
                    "type": row["type"],
                    "disconnects": row["disconnects"] or 0,
                    "minutes_unreachable": row["minutes_unreachable"] or 0,
                    "last_seen_ts": last_seen_ts,
                    "battery_low": bool(row["battery_low"]),
                    "score": score,
                    "age_hours": age_hours if last_seen_ts else None
                })

            devices.sort(key=lambda x: x["score"], reverse=True)
            return render_template("health.html", since=since, devices=devices)

        except Exception as e:
            logger.error("Error loading health data", error=str(e))
            return render_template("health.html", since=since, devices=[], error=str(e))

    @app.route("/tail")
    def tail():
        """Server-sent events stream for live event monitoring."""
        def event_stream():
            # Check if event processor is available
            if not event_processor:
                yield f"data: {json.dumps({'error': 'Event processor not initialized'})}\n\n"
                return

            last_id = db.get_max_event_id()
            last_poll = time.time()
            poll_interval = 2.0

            while True:
                try:
                    # Drain live events first for low latency
                    live_events = event_processor.drain_live_events(100)
                    for event in live_events:
                        yield f"data: {json.dumps(event)}\n\n"

                    # Periodic database poll as backup
                    if time.time() - last_poll >= poll_interval:
                        db_events = db.get_events_since_id(last_id)
                        for row in db_events:
                            last_id = row[0]  # Update last_id
                            payload = {
                                "ts": row[1],
                                "rid": row[2],
                                "rtype": row[3],
                                "raw": json.loads(row[4])
                            }
                            yield f"data: {json.dumps(payload)}\n\n"
                        last_poll = time.time()

                    time.sleep(0.5)

                except Exception as e:
                    logger.error("Error in event stream", error=str(e))
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    time.sleep(1)

        return Response(event_stream(), mimetype="text/event-stream")

    @app.route("/api/stats")
    def api_stats():
        """API endpoint for basic statistics."""
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()

                # Get basic counts
                cur.execute("SELECT COUNT(*) FROM events")
                total_events = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM devices")
                total_devices = cur.fetchone()[0]

                cur.execute("SELECT COUNT(DISTINCT rid) FROM diag WHERE day >= date('now', '-7 days')")
                active_devices = cur.fetchone()[0]

                # Get recent activity
                cur.execute("SELECT COUNT(*) FROM events WHERE ts >= datetime('now', '-1 hour')")
                events_last_hour = cur.fetchone()[0]

            return jsonify({
                "total_events": total_events,
                "total_devices": total_devices,
                "active_devices_7d": active_devices,
                "events_last_hour": events_last_hour,
                "bridge_ip": config.bridge_ip,
                "uptime": time.time() - app.start_time if hasattr(app, 'start_time') else 0
            })
        except Exception as e:
            logger.error("Error getting stats", error=str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/api/refresh-devices")
    def api_refresh_devices():
        """API endpoint to refresh device catalog."""
        try:
            if not event_processor:
                return jsonify({"error": "Event processor not initialized"}), 503

            event_processor.update_device_catalog()
            return jsonify({"status": "success", "message": "Device catalog updated"})
        except Exception as e:
            logger.error("Error refreshing devices", error=str(e))
            return jsonify({"error": str(e)}), 500

    return app


def main():
    """Main application entry point."""
    try:
        logger.info("Starting Hue Event Logger")

        # Create Flask app first
        app = create_app()
        app.start_time = time.time()

        # Try to initialize Hue connection (non-blocking)
        success = initialize_hue_connection()
        if not success:
            logger.warning("Hue connection failed, but web server will still start")
            logger.warning("Check the web interface for error details")

        # Start the web server regardless of Hue connection status
        logger.info("Starting web server", host=config.host, port=config.port)
        app.run(
            host=config.host,
            port=config.port,
            debug=config.debug,
            threaded=True
        )

    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.error("Application error", error=str(e), exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        if event_processor:
            event_processor.stop_event_stream()
        logger.info("Application stopped")


if __name__ == "__main__":
    main()
