"""Performance optimization utilities for Hue Event Logger."""
import sqlite3
import threading
import time
from typing import Dict, Any, Optional, List
from contextlib import contextmanager
from functools import lru_cache, wraps
from datetime import datetime, timedelta
import structlog

from config import config

logger = structlog.get_logger(__name__)


class DatabaseConnectionPool:
    """Simple connection pool for SQLite database."""
    
    def __init__(self, db_path: str, max_connections: int = 10):
        self.db_path = db_path
        self.max_connections = max_connections
        self._pool = []
        self._used_connections = set()
        self._lock = threading.RLock()
        
        # Pre-populate pool with initial connections
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize the connection pool."""
        with self._lock:
            for _ in range(min(3, self.max_connections)):  # Start with 3 connections
                conn = self._create_connection()
                self._pool.append(conn)
    
    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimization settings."""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0  # 30 second timeout
        )
        conn.row_factory = sqlite3.Row
        
        # Apply performance optimizations
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
        conn.execute("PRAGMA synchronous=NORMAL")  # Balanced safety/performance
        conn.execute("PRAGMA cache_size=10000")  # 10MB cache
        conn.execute("PRAGMA temp_store=MEMORY")  # Temp tables in memory
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory map
        
        return conn
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
        conn = None
        try:
            with self._lock:
                if self._pool:
                    conn = self._pool.pop()
                elif len(self._used_connections) < self.max_connections:
                    conn = self._create_connection()
                else:
                    # Wait for a connection to become available
                    logger.warning("Connection pool exhausted, waiting...")
                    
            if conn is None:
                # Fallback: wait and retry
                time.sleep(0.1)
                with self._lock:
                    if self._pool:
                        conn = self._pool.pop()
                    else:
                        # Emergency connection
                        conn = self._create_connection()
            
            with self._lock:
                self._used_connections.add(conn)
            
            yield conn
            
        finally:
            if conn:
                with self._lock:
                    self._used_connections.discard(conn)
                    if len(self._pool) < self.max_connections:
                        self._pool.append(conn)
                    else:
                        conn.close()
    
    def close_all(self):
        """Close all connections in the pool."""
        with self._lock:
            for conn in self._pool:
                conn.close()
            for conn in list(self._used_connections):
                conn.close()
            self._pool.clear()
            self._used_connections.clear()


class QueryCache:
    """Simple in-memory cache for database query results."""
    
    def __init__(self, default_ttl: int = 300):  # 5 minutes default
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        with self._lock:
            if key in self.cache:
                entry = self.cache[key]
                if datetime.now().timestamp() < entry['expires']:
                    return entry['value']
                else:
                    del self.cache[key]
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL."""
        ttl = ttl or self.default_ttl
        expires = datetime.now().timestamp() + ttl
        
        with self._lock:
            self.cache[key] = {
                'value': value,
                'expires': expires
            }
    
    def invalidate(self, pattern: Optional[str] = None) -> None:
        """Invalidate cache entries matching pattern."""
        with self._lock:
            if pattern is None:
                self.cache.clear()
            else:
                keys_to_remove = [k for k in self.cache.keys() if pattern in k]
                for key in keys_to_remove:
                    del self.cache[key]
    
    def cleanup_expired(self) -> int:
        """Remove expired entries and return count removed."""
        now = datetime.now().timestamp()
        removed = 0
        
        with self._lock:
            expired_keys = [
                k for k, v in self.cache.items()
                if now >= v['expires']
            ]
            for key in expired_keys:
                del self.cache[key]
                removed += 1
        
        return removed


class PerformanceOptimizer:
    """Main performance optimization manager."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection_pool = DatabaseConnectionPool(
            db_path, 
            max_connections=config.max_db_connections
        )
        self.query_cache = QueryCache(default_ttl=config.cache_ttl_seconds)
        
        # Start background cleanup task
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background task to cleanup expired cache entries."""
        def cleanup_worker():
            while True:
                try:
                    time.sleep(60)  # Run every minute
                    removed = self.query_cache.cleanup_expired()
                    if removed > 0:
                        logger.debug("Cache cleanup", removed_entries=removed)
                except Exception as e:
                    logger.error("Cache cleanup error", error=str(e))
        
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()
    
    @contextmanager
    def get_connection(self):
        """Get optimized database connection."""
        with self.connection_pool.get_connection() as conn:
            yield conn
    
    def cache_query_result(self, cache_key: str, query_func, ttl: Optional[int] = None):
        """Cache query result with automatic invalidation."""
        # Check cache first
        cached_result = self.query_cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Execute query and cache result
        result = query_func()
        self.query_cache.set(cache_key, result, ttl)
        return result
    
    def invalidate_cache(self, pattern: Optional[str] = None):
        """Invalidate cache entries."""
        self.query_cache.invalidate(pattern)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.query_cache._lock:
            total_entries = len(self.query_cache.cache)
            now = datetime.now().timestamp()
            expired_entries = sum(
                1 for v in self.query_cache.cache.values()
                if now >= v['expires']
            )
        
        return {
            'total_entries': total_entries,
            'expired_entries': expired_entries,
            'active_entries': total_entries - expired_entries
        }


def cached_query(cache_key_template: str, ttl: int = 300):
    """Decorator for caching database query results."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Generate cache key from template and arguments
            cache_key = cache_key_template.format(
                func_name=func.__name__,
                args=str(args),
                kwargs=str(sorted(kwargs.items()))
            )
            
            if hasattr(self, 'performance_optimizer'):
                return self.performance_optimizer.cache_query_result(
                    cache_key,
                    lambda: func(self, *args, **kwargs),
                    ttl
                )
            else:
                # Fallback without caching
                return func(self, *args, **kwargs)
        
        return wrapper
    return decorator


class BatchProcessor:
    """Utility for batching database operations."""
    
    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
        self._batch = []
        self._lock = threading.Lock()
    
    def add_operation(self, operation):
        """Add operation to batch."""
        with self._lock:
            self._batch.append(operation)
            if len(self._batch) >= self.batch_size:
                self._execute_batch()
    
    def _execute_batch(self):
        """Execute current batch of operations."""
        if not self._batch:
            return
        
        batch_to_execute = self._batch.copy()
        self._batch.clear()
        
        # Execute batch (implement specific logic in subclasses)
        self._process_batch(batch_to_execute)
    
    def _process_batch(self, operations):
        """Override in subclasses to implement specific batch processing."""
        raise NotImplementedError("Subclasses must implement _process_batch")
    
    def flush(self):
        """Force execution of current batch."""
        with self._lock:
            self._execute_batch()


class EventBatchProcessor(BatchProcessor):
    """Specialized batch processor for event insertions."""
    
    def __init__(self, db_connection_pool, batch_size: int = 50):
        super().__init__(batch_size)
        self.db_pool = db_connection_pool
    
    def _process_batch(self, operations):
        """Process batch of event insertions."""
        try:
            with self.db_pool.get_connection() as conn:
                cur = conn.cursor()
                
                # Prepare batch insert
                events_to_insert = []
                for op in operations:
                    if op['type'] == 'insert_event':
                        events_to_insert.append((
                            op['ts'], op['rid'], op['rtype'], op['raw']
                        ))
                
                if events_to_insert:
                    cur.executemany(
                        "INSERT INTO events(ts, rid, rtype, raw) VALUES(?,?,?,?)",
                        events_to_insert
                    )
                    conn.commit()
                    logger.debug("Batch inserted events", count=len(events_to_insert))
                    
        except Exception as e:
            logger.error("Batch processing failed", error=str(e))


def optimize_database_indexes(db_path: str):
    """Create additional indexes for better query performance."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_events_ts_rid ON events(ts, rid)",
        "CREATE INDEX IF NOT EXISTS idx_events_rtype_ts ON events(rtype, ts)", 
        "CREATE INDEX IF NOT EXISTS idx_diag_rid_day ON diag(rid, day)",
        "CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(type)",
        "CREATE INDEX IF NOT EXISTS idx_events_ts_desc ON events(ts DESC)"
    ]
    
    try:
        conn = sqlite3.connect(db_path)
        for index_sql in indexes:
            conn.execute(index_sql)
        conn.commit()
        conn.close()
        logger.info("Database indexes optimized")
    except Exception as e:
        logger.error("Failed to optimize indexes", error=str(e))


def analyze_database_performance(db_path: str) -> Dict[str, Any]:
    """Analyze database performance and return statistics."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Get table statistics
        stats = {}
        
        # Table row counts
        for table in ['events', 'devices', 'diag']:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            stats[f"{table}_count"] = cur.fetchone()[0]
        
        # Database size
        cur.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
        stats['db_size_bytes'] = cur.fetchone()[0]
        
        # Index usage
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
        stats['indexes'] = [row[0] for row in cur.fetchall()]
        
        # Recent activity
        cur.execute("SELECT COUNT(*) FROM events WHERE ts >= datetime('now', '-1 hour')")
        stats['events_last_hour'] = cur.fetchone()[0]
        
        conn.close()
        return stats
        
    except Exception as e:
        logger.error("Database analysis failed", error=str(e))
        return {"error": str(e)}