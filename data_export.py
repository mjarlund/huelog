"""Data export functionality for Hue Event Logger."""
import csv
import json
import io
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timezone, date, timedelta
from flask import Response, request
import structlog

from database import HueDatabase
from error_handling import log_exceptions, log_operation

logger = structlog.get_logger(__name__)


class DataExporter:
    """Handles data export in various formats."""
    
    def __init__(self, db: HueDatabase):
        self.db = db
    
    def export_events_csv(self, 
                         query: Optional[str] = None, 
                         limit: int = 1000,
                         since: Optional[str] = None) -> str:
        """Export events to CSV format."""
        
        with log_operation("export_events_csv", query=query, limit=limit, since=since):
            # Get events data
            if since:
                events = self._get_events_since_date(query, limit, since)
            else:
                events = self.db.get_events(query, limit)
            
            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['timestamp', 'resource_id', 'event_type', 'event_data'])
            
            # Write data rows
            for event in events:
                # Parse JSON data for more readable CSV
                try:
                    raw_data = json.loads(event['raw'])
                    # Flatten common fields for better CSV representation
                    flattened_data = self._flatten_event_data(raw_data)
                except (json.JSONDecodeError, TypeError):
                    flattened_data = event['raw']
                
                writer.writerow([
                    event['ts'],
                    event['rid'] or '',
                    event['rtype'] or '',
                    json.dumps(flattened_data) if isinstance(flattened_data, dict) else str(flattened_data)
                ])
            
            return output.getvalue()
    
    def export_device_health_csv(self, since: Optional[str] = None) -> str:
        """Export device health data to CSV format."""
        
        if not since:
            since = (date.today() - timedelta(days=7)).isoformat()
        
        with log_operation("export_device_health_csv", since=since):
            health_data = self.db.get_device_health(since)
            
            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'resource_id', 'device_name', 'device_type', 'disconnects', 
                'minutes_unreachable', 'last_seen_timestamp', 'battery_low', 
                'health_score', 'age_hours'
            ])
            
            now_sec = int(datetime.utcnow().timestamp())
            
            # Write data rows
            for row in health_data:
                last_seen_ts = row["last_seen_ts"] or ""
                age_hours = 0
                
                if last_seen_ts:
                    try:
                        dt_obj = datetime.fromisoformat(last_seen_ts.replace("Z", ""))
                        age_hours = (now_sec - int(dt_obj.timestamp())) / 3600
                    except Exception:
                        age_hours = 0
                
                # Calculate health score
                age_flag = 1 if age_hours > 1 else 0
                score = (
                    3 * (row["disconnects"] or 0) +
                    2 * ((row["minutes_unreachable"] or 0) // 10) +
                    2 * age_flag +
                    2 * (row["battery_low"] or 0)
                )
                
                writer.writerow([
                    row["rid"],
                    row["name"],
                    row["type"], 
                    row["disconnects"] or 0,
                    row["minutes_unreachable"] or 0,
                    last_seen_ts,
                    bool(row["battery_low"]),
                    score,
                    round(age_hours, 2) if age_hours > 0 else 0
                ])
            
            return output.getvalue()
    
    def export_events_json(self, 
                          query: Optional[str] = None, 
                          limit: int = 1000,
                          since: Optional[str] = None) -> Dict[str, Any]:
        """Export events to JSON format."""
        
        with log_operation("export_events_json", query=query, limit=limit, since=since):
            # Get events data
            if since:
                events = self._get_events_since_date(query, limit, since)
            else:
                events = self.db.get_events(query, limit)
            
            # Convert to JSON-friendly format
            events_list = []
            for event in events:
                try:
                    raw_data = json.loads(event['raw']) if isinstance(event['raw'], str) else event['raw']
                except (json.JSONDecodeError, TypeError):
                    raw_data = str(event['raw'])
                
                events_list.append({
                    'timestamp': event['ts'],
                    'resource_id': event['rid'],
                    'event_type': event['rtype'],
                    'event_data': raw_data
                })
            
            return {
                'metadata': {
                    'export_timestamp': datetime.now(timezone.utc).isoformat(),
                    'total_events': len(events_list),
                    'query': query,
                    'limit': limit,
                    'since': since
                },
                'events': events_list
            }
    
    def export_device_health_json(self, since: Optional[str] = None) -> Dict[str, Any]:
        """Export device health data to JSON format."""
        
        if not since:
            since = (date.today() - timedelta(days=7)).isoformat()
        
        with log_operation("export_device_health_json", since=since):
            health_data = self.db.get_device_health(since)
            
            now_sec = int(datetime.utcnow().timestamp())
            devices_list = []
            
            for row in health_data:
                last_seen_ts = row["last_seen_ts"] or ""
                age_hours = 0
                
                if last_seen_ts:
                    try:
                        dt_obj = datetime.fromisoformat(last_seen_ts.replace("Z", ""))
                        age_hours = (now_sec - int(dt_obj.timestamp())) / 3600
                    except Exception:
                        age_hours = 0
                
                # Calculate health score  
                age_flag = 1 if age_hours > 1 else 0
                score = (
                    3 * (row["disconnects"] or 0) +
                    2 * ((row["minutes_unreachable"] or 0) // 10) +
                    2 * age_flag +
                    2 * (row["battery_low"] or 0)
                )
                
                devices_list.append({
                    'resource_id': row["rid"],
                    'device_name': row["name"],
                    'device_type': row["type"],
                    'disconnects': row["disconnects"] or 0,
                    'minutes_unreachable': row["minutes_unreachable"] or 0,
                    'last_seen_timestamp': last_seen_ts,
                    'battery_low': bool(row["battery_low"]),
                    'health_score': score,
                    'age_hours': round(age_hours, 2) if age_hours > 0 else 0
                })
            
            return {
                'metadata': {
                    'export_timestamp': datetime.now(timezone.utc).isoformat(),
                    'total_devices': len(devices_list),
                    'since': since,
                    'health_score_algorithm': '3*disconnects + 2*(downtime_minutes/10) + 2*age_flag + 2*battery_low'
                },
                'devices': devices_list
            }
    
    def _get_events_since_date(self, query: Optional[str], limit: int, since: str) -> List[Dict]:
        """Get events since a specific date."""
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            
            if query:
                cur.execute("""
                    SELECT ts, rid, rtype, raw FROM events
                    WHERE ts >= ? AND (raw LIKE ? OR rid LIKE ? OR rtype LIKE ?)
                    ORDER BY id DESC LIMIT ?
                """, (since, f"%{query}%", f"%{query}%", f"%{query}%", limit))
            else:
                cur.execute("""
                    SELECT ts, rid, rtype, raw FROM events
                    WHERE ts >= ?
                    ORDER BY id DESC LIMIT ?
                """, (since, limit))
            
            return [dict(row) for row in cur.fetchall()]
    
    def _flatten_event_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested event data for better CSV representation."""
        flattened = {}
        
        def _flatten_recursive(obj: Any, prefix: str = '') -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_key = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, (dict, list)) and len(str(value)) > 100:
                        # Keep complex nested structures as JSON strings
                        flattened[new_key] = json.dumps(value)
                    elif isinstance(value, dict):
                        _flatten_recursive(value, new_key)
                    else:
                        flattened[new_key] = value
            elif isinstance(obj, list):
                flattened[prefix] = json.dumps(obj)
            else:
                flattened[prefix] = obj
        
        _flatten_recursive(data)
        return flattened


def create_export_routes(app, db: HueDatabase):
    """Create export routes for the Flask app."""
    
    exporter = DataExporter(db)
    
    @app.route("/api/export/events.csv")
    @log_exceptions("export")
    def export_events_csv():
        """Export events as CSV file."""
        query = request.args.get("q", "").strip()
        limit = min(request.args.get("limit", 1000, type=int), 10000)
        since = request.args.get("since", "").strip()
        
        csv_data = exporter.export_events_csv(
            query=query or None,
            limit=limit,
            since=since or None
        )
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hue_events_{timestamp}.csv"
        
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    @app.route("/api/export/events.json")
    @log_exceptions("export")
    def export_events_json():
        """Export events as JSON file."""
        query = request.args.get("q", "").strip()
        limit = min(request.args.get("limit", 1000, type=int), 10000)
        since = request.args.get("since", "").strip()
        
        json_data = exporter.export_events_json(
            query=query or None,
            limit=limit,
            since=since or None
        )
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hue_events_{timestamp}.json"
        
        return Response(
            json.dumps(json_data, indent=2, default=str),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    @app.route("/api/export/health.csv")
    @log_exceptions("export")
    def export_health_csv():
        """Export device health as CSV file."""
        since = request.args.get("since", "").strip()
        
        csv_data = exporter.export_device_health_csv(since=since or None)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hue_device_health_{timestamp}.csv"
        
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    @app.route("/api/export/health.json")
    @log_exceptions("export")
    def export_health_json():
        """Export device health as JSON file."""
        since = request.args.get("since", "").strip()
        
        json_data = exporter.export_device_health_json(since=since or None)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hue_device_health_{timestamp}.json"
        
        return Response(
            json.dumps(json_data, indent=2, default=str),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    @app.route("/api/export")
    def export_info():
        """Get information about available export endpoints."""
        return {
            "available_exports": {
                "events": {
                    "csv": "/api/export/events.csv",
                    "json": "/api/export/events.json",
                    "parameters": {
                        "q": "Filter query (optional)",
                        "limit": "Maximum number of events (max 10000, default 1000)",
                        "since": "ISO date string to filter events from (optional)"
                    }
                },
                "device_health": {
                    "csv": "/api/export/health.csv", 
                    "json": "/api/export/health.json",
                    "parameters": {
                        "since": "ISO date string for health data period (optional, default 7 days ago)"
                    }
                }
            },
            "formats": {
                "csv": "Comma-separated values, suitable for Excel/spreadsheets",
                "json": "Structured JSON with metadata, suitable for programmatic processing"
            },
            "examples": [
                "/api/export/events.csv?q=motion&limit=500",
                "/api/export/events.json?since=2023-10-01",
                "/api/export/health.csv?since=2023-10-01",
                "/api/export/health.json"
            ]
        }