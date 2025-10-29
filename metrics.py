"""Metrics collection and monitoring for Hue Event Logger."""
import time
import threading
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import structlog
from dataclasses import dataclass, field
from collections import defaultdict, deque

logger = structlog.get_logger(__name__)


@dataclass
class MetricCounter:
    """Simple counter metric."""
    value: int = 0
    
    def increment(self, amount: int = 1):
        """Increment the counter."""
        self.value += amount
    
    def get(self) -> int:
        """Get current value."""
        return self.value


@dataclass 
class MetricGauge:
    """Gauge metric for current values."""
    value: float = 0.0
    
    def set(self, value: float):
        """Set the gauge value."""
        self.value = value
    
    def get(self) -> float:
        """Get current value."""
        return self.value


@dataclass
class MetricHistogram:
    """Simple histogram for timing data."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    total: float = 0.0
    count: int = 0
    
    def observe(self, value: float):
        """Record a new observation."""
        self.samples.append(value)
        self.total += value
        self.count += 1
    
    def get_stats(self) -> Dict[str, float]:
        """Get histogram statistics."""
        if not self.samples:
            return {"count": 0, "sum": 0.0, "avg": 0.0, "min": 0.0, "max": 0.0}
        
        samples_list = list(self.samples)
        return {
            "count": self.count,
            "sum": self.total,
            "avg": self.total / self.count if self.count > 0 else 0.0,
            "min": min(samples_list),
            "max": max(samples_list),
            "recent_avg": sum(samples_list) / len(samples_list) if samples_list else 0.0
        }


class MetricsCollector:
    """Collects and manages application metrics."""
    
    def __init__(self):
        self.start_time = time.time()
        self._lock = threading.RLock()
        
        # Core metrics
        self.counters = defaultdict(MetricCounter)
        self.gauges = defaultdict(MetricGauge) 
        self.histograms = defaultdict(MetricHistogram)
        
        # Initialize common metrics
        self._init_metrics()
    
    def _init_metrics(self):
        """Initialize common application metrics."""
        # Event processing metrics
        self.counters["events_processed_total"]
        self.counters["events_failed_total"]
        self.counters["database_operations_total"]
        self.counters["database_errors_total"]
        self.counters["hue_api_requests_total"]
        self.counters["hue_api_errors_total"]
        self.counters["http_requests_total"]
        
        # Gauges for current state
        self.gauges["live_events_queue_size"]
        self.gauges["active_database_connections"]
        self.gauges["devices_total"]
        self.gauges["events_last_hour"]
        
        # Histograms for timing
        self.histograms["event_processing_duration_seconds"]
        self.histograms["database_query_duration_seconds"]
        self.histograms["hue_api_request_duration_seconds"]
        self.histograms["http_request_duration_seconds"]

    def increment_counter(self, name: str, amount: int = 1, labels: Optional[Dict[str, str]] = None):
        """Increment a counter metric."""
        with self._lock:
            metric_name = self._build_metric_name(name, labels)
            self.counters[metric_name].increment(amount)
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Set a gauge metric."""
        with self._lock:
            metric_name = self._build_metric_name(name, labels)
            self.gauges[metric_name].set(value)
    
    def observe_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a histogram observation."""
        with self._lock:
            metric_name = self._build_metric_name(name, labels)
            self.histograms[metric_name].observe(value)
    
    def _build_metric_name(self, name: str, labels: Optional[Dict[str, str]] = None) -> str:
        """Build metric name with labels."""
        if not labels:
            return name
        
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all current metrics."""
        with self._lock:
            metrics = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "uptime_seconds": time.time() - self.start_time,
                "counters": {name: counter.get() for name, counter in self.counters.items()},
                "gauges": {name: gauge.get() for name, gauge in self.gauges.items()},
                "histograms": {name: hist.get_stats() for name, hist in self.histograms.items()}
            }
            
        return metrics
    
    def get_prometheus_format(self) -> str:
        """Get metrics in Prometheus exposition format."""
        lines = []
        
        # Add metadata
        lines.append("# HELP hue_uptime_seconds Application uptime")
        lines.append("# TYPE hue_uptime_seconds gauge")
        lines.append(f"hue_uptime_seconds {time.time() - self.start_time}")
        lines.append("")
        
        with self._lock:
            # Counters
            for name, counter in self.counters.items():
                base_name = name.split('{')[0]  # Remove labels for help text
                lines.append(f"# HELP {base_name} Counter metric")
                lines.append(f"# TYPE {base_name} counter")
                lines.append(f"{name} {counter.get()}")
            
            # Gauges
            for name, gauge in self.gauges.items():
                base_name = name.split('{')[0]
                lines.append(f"# HELP {base_name} Gauge metric")
                lines.append(f"# TYPE {base_name} gauge")
                lines.append(f"{name} {gauge.get()}")
            
            # Histograms (simplified)
            for name, histogram in self.histograms.items():
                base_name = name.split('{')[0]
                stats = histogram.get_stats()
                
                lines.append(f"# HELP {base_name} Histogram metric")
                lines.append(f"# TYPE {base_name} histogram")
                lines.append(f"{base_name}_count {stats['count']}")
                lines.append(f"{base_name}_sum {stats['sum']}")
                
                # Add some basic percentiles if we have samples
                if stats['count'] > 0:
                    lines.append(f"{base_name}_min {stats['min']}")
                    lines.append(f"{base_name}_max {stats['max']}")
                    lines.append(f"{base_name}_avg {stats['avg']}")
        
        return "\n".join(lines)

    def record_event_processed(self, event_type: str, duration: float, success: bool = True):
        """Record event processing metrics."""
        labels = {"event_type": event_type}
        
        if success:
            self.increment_counter("events_processed_total", labels=labels)
        else:
            self.increment_counter("events_failed_total", labels=labels)
        
        self.observe_histogram("event_processing_duration_seconds", duration, labels=labels)

    def record_database_operation(self, operation: str, duration: float, success: bool = True):
        """Record database operation metrics."""
        labels = {"operation": operation}
        
        if success:
            self.increment_counter("database_operations_total", labels=labels)
        else:
            self.increment_counter("database_errors_total", labels=labels)
        
        self.observe_histogram("database_query_duration_seconds", duration, labels=labels)

    def record_hue_api_request(self, endpoint: str, duration: float, status_code: int):
        """Record Hue API request metrics."""
        labels = {"endpoint": endpoint, "status": str(status_code)}
        
        self.increment_counter("hue_api_requests_total", labels=labels)
        
        if status_code >= 400:
            self.increment_counter("hue_api_errors_total", labels=labels)
        
        self.observe_histogram("hue_api_request_duration_seconds", duration, labels=labels)

    def record_http_request(self, method: str, path: str, status_code: int, duration: float):
        """Record HTTP request metrics."""
        labels = {"method": method, "path": path, "status": str(status_code)}
        
        self.increment_counter("http_requests_total", labels=labels)
        self.observe_histogram("http_request_duration_seconds", duration, labels=labels)

    def update_queue_size(self, size: int):
        """Update live events queue size."""
        self.set_gauge("live_events_queue_size", size)

    def update_device_count(self, count: int):
        """Update total device count."""
        self.set_gauge("devices_total", count)

    def update_events_last_hour(self, count: int):
        """Update events in last hour count."""
        self.set_gauge("events_last_hour", count)


class TimingContext:
    """Context manager for timing operations."""
    
    def __init__(self, metrics: MetricsCollector, metric_name: str, labels: Optional[Dict[str, str]] = None):
        self.metrics = metrics
        self.metric_name = metric_name
        self.labels = labels
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.metrics.observe_histogram(self.metric_name, duration, self.labels)


# Global metrics instance
metrics = MetricsCollector()


def timing(metric_name: str, labels: Optional[Dict[str, str]] = None):
    """Decorator for timing function execution."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with TimingContext(metrics, metric_name, labels):
                return func(*args, **kwargs)
        return wrapper
    return decorator