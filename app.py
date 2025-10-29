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
from metrics import metrics, TimingContext
from health import create_health_checker
from error_handling import (
    setup_request_logging, RequestContextManager, ErrorHandler,
    log_exceptions, log_operation
)
from data_export import create_export_routes

# Initialize colorama for colored console output
colorama.init()

# Setup enhanced logging with request context
setup_request_logging()

logger = structlog.get_logger(__name__)

# Global instances
db = None
event_processor = None
health_checker = None


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
    global db, health_checker

    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'hue-event-logger-secret'

    # Initialize database
    db = HueDatabase()

    # Initialize health checker
    health_checker = create_health_checker(db=db, event_processor=event_processor)

    # Initialize error handling
    error_handler = ErrorHandler(app)

    # Request context and metrics middleware
    @app.before_request
    def before_request():
        request.start_time = time.time()
        RequestContextManager.before_request()

    @app.after_request
    def after_request(response):
        # Metrics tracking
        if hasattr(request, 'start_time'):
            duration = time.time() - request.start_time
            metrics.record_http_request(
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                duration=duration
            )
        
        # Request logging
        return RequestContextManager.after_request(response)

    # Routes
    @app.route("/")
    @log_exceptions("web")
    def index():
        """Main events page with filtering."""
        query = request.args.get("q", "", type=str).strip()
        limit = min(request.args.get("limit", 200, type=int), 10000)  # Cap at 10k

        with log_operation("load_events", query=query, limit=limit):
            events = db.get_events(query, limit)
            return render_template("index.html", events=events, q=query, limit=limit)

    @app.route("/health")
    @log_exceptions("web")
    def health():
        """Device health dashboard."""
        since = request.args.get("since")
        if not since:
            since = (dt.date.today() - dt.timedelta(days=7)).isoformat()

        with log_operation("load_health_data", since=since):
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
        with TimingContext(metrics, "http_request_duration_seconds", {"endpoint": "stats"}):
            try:
                with TimingContext(metrics, "database_query_duration_seconds", {"operation": "stats"}):
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

                # Update metrics
                metrics.update_device_count(total_devices)
                metrics.update_events_last_hour(events_last_hour)

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
                metrics.increment_counter("database_errors_total", labels={"operation": "stats"})
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

    @app.route("/resource/zigbee_connectivity")
    def resource_zigbee_connectivity():
        """API endpoint to get zigbee connectivity information."""
        try:
            if not event_processor:
                return jsonify({"error": "Event processor not initialized"}), 503

            connectivity_data = event_processor.get_zigbee_connectivity()

            # Enhance the data with device names from our database
            enhanced_data = []
            for item in connectivity_data:
                device_id = item.get("id")
                if device_id:
                    # Try to get device name from database
                    device_info = db.get_device_info(device_id)
                    enhanced_item = item.copy()
                    if device_info:
                        enhanced_item["device_name"] = device_info.get("name", device_id)
                        enhanced_item["device_type"] = device_info.get("type", "unknown")
                    else:
                        enhanced_item["device_name"] = device_id
                        enhanced_item["device_type"] = "unknown"
                    enhanced_data.append(enhanced_item)
                else:
                    enhanced_data.append(item)

            return jsonify({
                "data": enhanced_data,
                "count": len(enhanced_data),
                "timestamp": dt.datetime.utcnow().isoformat() + "Z"
            })
        except Exception as e:
            logger.error("Error getting zigbee connectivity", error=str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/resource/zgp_connectivity")
    def resource_zgp_connectivity():
        """API endpoint to get ZGP (Zigbee Green Power) connectivity information."""
        try:
            if not event_processor:
                return jsonify({"error": "Event processor not initialized"}), 503

            connectivity_data = event_processor.get_zgp_connectivity()

            # Enhance the data with device names from our database
            enhanced_data = []
            for item in connectivity_data:
                device_id = item.get("id")
                if device_id:
                    # Try to get device name from database
                    device_info = db.get_device_info(device_id)
                    enhanced_item = item.copy()
                    if device_info:
                        enhanced_item["device_name"] = device_info.get("name", device_id)
                        enhanced_item["device_type"] = device_info.get("type", "unknown")
                    else:
                        enhanced_item["device_name"] = device_id
                        enhanced_item["device_type"] = "unknown"
                    enhanced_data.append(enhanced_item)
                else:
                    enhanced_data.append(item)

            return jsonify({
                "data": enhanced_data,
                "count": len(enhanced_data),
                "timestamp": dt.datetime.utcnow().isoformat() + "Z",
                "protocol": "zgp"
            })
        except Exception as e:
            logger.error("Error getting ZGP connectivity", error=str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/metrics")
    def metrics_endpoint():
        """Prometheus-style metrics endpoint."""
        return Response(
            metrics.get_prometheus_format(),
            mimetype="text/plain; version=0.0.4; charset=utf-8"
        )

    @app.route("/api/metrics")
    def api_metrics():
        """JSON metrics endpoint."""
        return jsonify(metrics.get_all_metrics())

    @app.route("/health")
    def health_endpoint():
        """Health check endpoint.""" 
        health_status = health_checker.get_overall_status()
        
        # Return appropriate HTTP status code
        if health_status["status"] == "critical":
            status_code = 503  # Service Unavailable
        elif health_status["status"] == "warning":
            status_code = 200  # OK but with warnings
        else:
            status_code = 200  # OK
        
        return jsonify(health_status), status_code

    @app.route("/api/health/<check_name>")
    def single_health_check(check_name):
        """Run a specific health check."""
        result = health_checker.run_check(check_name)
        
        if result.status.value == "unknown":
            status_code = 404
        elif result.status.value == "critical":
            status_code = 503
        else:
            status_code = 200
            
        return jsonify({
            "name": result.name,
            "status": result.status.value,
            "message": result.message,
            "details": result.details,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None
        }), status_code

    @app.route("/api/performance")
    @log_exceptions("performance")
    def api_performance():
        """API endpoint for performance statistics."""
        try:
            performance_stats = db.get_performance_stats()
            return jsonify(performance_stats)
        except Exception as e:
            logger.error("Error getting performance stats", error=str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/api/cache/invalidate", methods=["POST"])
    @log_exceptions("cache")
    def api_invalidate_cache():
        """API endpoint to manually invalidate cache."""
        try:
            pattern = request.get_json().get("pattern") if request.is_json else None
            db.invalidate_cache(pattern)
            return jsonify({"status": "success", "message": "Cache invalidated"})
        except Exception as e:
            logger.error("Error invalidating cache", error=str(e))
            return jsonify({"error": str(e)}), 500

    # Add export routes
    create_export_routes(app, db)

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
