"""Enhanced health check system for Hue Event Logger."""
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)


class HealthStatus(Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    WARNING = "warning" 
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Individual health check result."""
    name: str
    status: HealthStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


class HealthChecker:
    """Comprehensive health checking system."""
    
    def __init__(self, db=None, event_processor=None):
        self.db = db
        self.event_processor = event_processor
        self._checks = {}
        self._last_results = {}
        self._lock = threading.RLock()
        
        # Health check thresholds
        self.thresholds = {
            "database_response_time_ms": 1000,
            "event_queue_size_warning": 8000,
            "event_queue_size_critical": 9500,
            "events_last_hour_min": 1,
            "hue_connection_timeout_seconds": 10,
            "memory_usage_warning_percent": 80,
            "memory_usage_critical_percent": 90
        }
    
    def register_check(self, name: str, check_func, critical: bool = False):
        """Register a health check function."""
        with self._lock:
            self._checks[name] = {
                "func": check_func,
                "critical": critical,
                "last_run": None,
                "last_result": None
            }
    
    def run_check(self, name: str) -> HealthCheck:
        """Run a specific health check."""
        if name not in self._checks:
            return HealthCheck(
                name=name,
                status=HealthStatus.UNKNOWN,
                message=f"Unknown health check: {name}"
            )
        
        check_info = self._checks[name]
        
        try:
            start_time = time.time()
            result = check_info["func"]()
            duration = time.time() - start_time
            
            # Update check info
            check_info["last_run"] = datetime.now(timezone.utc)
            check_info["last_result"] = result
            
            # Add timing to result details
            if result.details is None:
                result.details = {}
            result.details["check_duration_ms"] = round(duration * 1000, 2)
            
            with self._lock:
                self._last_results[name] = result
            
            return result
            
        except Exception as e:
            logger.error("Health check failed", check_name=name, error=str(e))
            error_result = HealthCheck(
                name=name,
                status=HealthStatus.CRITICAL,
                message=f"Health check failed: {str(e)}",
                details={"error_type": type(e).__name__}
            )
            
            with self._lock:
                self._last_results[name] = error_result
            
            return error_result
    
    def run_all_checks(self) -> Dict[str, HealthCheck]:
        """Run all registered health checks."""
        results = {}
        
        for name in self._checks:
            results[name] = self.run_check(name)
        
        return results
    
    def get_overall_status(self) -> Dict[str, Any]:
        """Get overall system health status."""
        results = self.run_all_checks()
        
        # Determine overall status
        has_critical = any(result.status == HealthStatus.CRITICAL for result in results.values())
        has_warning = any(result.status == HealthStatus.WARNING for result in results.values())
        
        if has_critical:
            overall_status = HealthStatus.CRITICAL
        elif has_warning:
            overall_status = HealthStatus.WARNING
        else:
            overall_status = HealthStatus.HEALTHY
        
        # Count by status
        status_counts = {
            "healthy": sum(1 for r in results.values() if r.status == HealthStatus.HEALTHY),
            "warning": sum(1 for r in results.values() if r.status == HealthStatus.WARNING), 
            "critical": sum(1 for r in results.values() if r.status == HealthStatus.CRITICAL),
            "unknown": sum(1 for r in results.values() if r.status == HealthStatus.UNKNOWN)
        }
        
        return {
            "status": overall_status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {name: {
                "status": result.status.value,
                "message": result.message,
                "details": result.details,
                "timestamp": result.timestamp.isoformat() if result.timestamp else None
            } for name, result in results.items()},
            "summary": {
                "total_checks": len(results),
                "status_counts": status_counts
            }
        }
    
    def check_database(self) -> HealthCheck:
        """Check database connectivity and performance."""
        if not self.db:
            return HealthCheck(
                name="database",
                status=HealthStatus.CRITICAL,
                message="Database not initialized"
            )
        
        try:
            start_time = time.time()
            
            # Test basic connectivity
            with self.db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                result = cur.fetchone()
                
                if result[0] != 1:
                    return HealthCheck(
                        name="database", 
                        status=HealthStatus.CRITICAL,
                        message="Database connectivity test failed"
                    )
                
                # Get some basic stats
                cur.execute("SELECT COUNT(*) FROM events")
                event_count = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM devices")
                device_count = cur.fetchone()[0]
            
            response_time_ms = (time.time() - start_time) * 1000
            
            # Check response time
            if response_time_ms > self.thresholds["database_response_time_ms"]:
                status = HealthStatus.WARNING
                message = f"Database response time high: {response_time_ms:.2f}ms"
            else:
                status = HealthStatus.HEALTHY
                message = "Database is healthy"
            
            return HealthCheck(
                name="database",
                status=status,
                message=message,
                details={
                    "response_time_ms": round(response_time_ms, 2),
                    "event_count": event_count,
                    "device_count": device_count,
                    "db_path": self.db.db_path
                }
            )
            
        except Exception as e:
            return HealthCheck(
                name="database",
                status=HealthStatus.CRITICAL,
                message=f"Database error: {str(e)}",
                details={"error_type": type(e).__name__}
            )
    
    def check_event_processor(self) -> HealthCheck:
        """Check event processor status."""
        if not self.event_processor:
            return HealthCheck(
                name="event_processor",
                status=HealthStatus.WARNING,
                message="Event processor not initialized"
            )
        
        try:
            # Check if processor is running
            if not self.event_processor.is_running:
                return HealthCheck(
                    name="event_processor",
                    status=HealthStatus.CRITICAL, 
                    message="Event processor is not running"
                )
            
            # Check queue size
            queue_size = self.event_processor.live_tail_events.qsize()
            
            if queue_size >= self.thresholds["event_queue_size_critical"]:
                status = HealthStatus.CRITICAL
                message = f"Event queue critically full: {queue_size} events"
            elif queue_size >= self.thresholds["event_queue_size_warning"]:
                status = HealthStatus.WARNING
                message = f"Event queue getting full: {queue_size} events"
            else:
                status = HealthStatus.HEALTHY
                message = "Event processor is healthy"
            
            return HealthCheck(
                name="event_processor",
                status=status,
                message=message,
                details={
                    "is_running": self.event_processor.is_running,
                    "queue_size": queue_size,
                    "queue_maxsize": self.event_processor.live_tail_events.maxsize,
                    "bridge_ip": self.event_processor.bridge_ip
                }
            )
            
        except Exception as e:
            return HealthCheck(
                name="event_processor",
                status=HealthStatus.CRITICAL,
                message=f"Event processor error: {str(e)}",
                details={"error_type": type(e).__name__}
            )
    
    def check_recent_activity(self) -> HealthCheck:
        """Check for recent event activity."""
        if not self.db:
            return HealthCheck(
                name="recent_activity",
                status=HealthStatus.UNKNOWN,
                message="Cannot check activity - database not available"
            )
        
        try:
            with self.db.get_connection() as conn:
                cur = conn.cursor()
                
                # Check events in last hour
                cur.execute("""
                    SELECT COUNT(*) FROM events 
                    WHERE ts >= datetime('now', '-1 hour')
                """)
                events_last_hour = cur.fetchone()[0]
                
                # Check events in last 5 minutes  
                cur.execute("""
                    SELECT COUNT(*) FROM events
                    WHERE ts >= datetime('now', '-5 minutes')
                """)
                events_last_5min = cur.fetchone()[0]
                
                # Check last event timestamp
                cur.execute("SELECT MAX(ts) FROM events")
                last_event_ts = cur.fetchone()[0]
            
            # Determine status based on activity
            if events_last_5min > 0:
                status = HealthStatus.HEALTHY
                message = "Recent activity detected"
            elif events_last_hour >= self.thresholds["events_last_hour_min"]:
                status = HealthStatus.HEALTHY  
                message = "Normal activity levels"
            else:
                status = HealthStatus.WARNING
                message = "Low or no recent activity"
            
            return HealthCheck(
                name="recent_activity",
                status=status,
                message=message,
                details={
                    "events_last_hour": events_last_hour,
                    "events_last_5min": events_last_5min,
                    "last_event_timestamp": last_event_ts
                }
            )
            
        except Exception as e:
            return HealthCheck(
                name="recent_activity",
                status=HealthStatus.CRITICAL,
                message=f"Activity check failed: {str(e)}",
                details={"error_type": type(e).__name__}
            )
    
    def check_hue_bridge_connectivity(self) -> HealthCheck:
        """Check connectivity to Hue bridge."""
        if not self.event_processor:
            return HealthCheck(
                name="hue_bridge",
                status=HealthStatus.UNKNOWN,
                message="Cannot check Hue bridge - event processor not available"
            )
        
        try:
            import requests
            
            # Simple connectivity test
            start_time = time.time()
            
            test_url = f"https://{self.event_processor.bridge_ip}/clip/v2/resource/device"
            response = requests.get(
                test_url,
                headers={"hue-application-key": self.event_processor.app_key},
                verify=self.event_processor.verify_tls,
                timeout=self.thresholds["hue_connection_timeout_seconds"]
            )
            
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                device_count = len(data.get("data", []))
                
                return HealthCheck(
                    name="hue_bridge",
                    status=HealthStatus.HEALTHY,
                    message="Hue bridge is accessible",
                    details={
                        "response_time_ms": round(duration * 1000, 2),
                        "status_code": response.status_code,
                        "bridge_device_count": device_count,
                        "bridge_ip": self.event_processor.bridge_ip
                    }
                )
            else:
                return HealthCheck(
                    name="hue_bridge",
                    status=HealthStatus.WARNING,
                    message=f"Hue bridge returned status {response.status_code}",
                    details={
                        "response_time_ms": round(duration * 1000, 2),
                        "status_code": response.status_code,
                        "bridge_ip": self.event_processor.bridge_ip
                    }
                )
                
        except Exception as e:
            return HealthCheck(
                name="hue_bridge",
                status=HealthStatus.CRITICAL,
                message=f"Hue bridge unreachable: {str(e)}",
                details={
                    "error_type": type(e).__name__,
                    "bridge_ip": self.event_processor.bridge_ip if self.event_processor else "unknown"
                }
            )


def create_health_checker(db=None, event_processor=None) -> HealthChecker:
    """Create and configure a health checker with default checks."""
    checker = HealthChecker(db=db, event_processor=event_processor)
    
    # Register default checks
    checker.register_check("database", checker.check_database, critical=True)
    checker.register_check("event_processor", checker.check_event_processor, critical=True)
    checker.register_check("recent_activity", checker.check_recent_activity, critical=False)
    checker.register_check("hue_bridge", checker.check_hue_bridge_connectivity, critical=False)
    
    return checker