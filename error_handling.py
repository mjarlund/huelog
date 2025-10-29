"""Enhanced logging and error handling utilities."""
import uuid
import sys
import traceback
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from functools import wraps
from contextlib import contextmanager

import structlog
from flask import request, g


def setup_request_logging():
    """Setup request-scoped logging with correlation IDs."""
    
    def configure_logger(_, __, event_dict):
        """Add request context to log events."""
        # Add request ID if available
        if hasattr(g, 'request_id'):
            event_dict['request_id'] = g.request_id
        
        # Add request context if available
        if request and hasattr(request, 'method'):
            event_dict.update({
                'method': request.method,
                'path': request.path,
                'remote_addr': request.remote_addr,
                'user_agent': request.headers.get('User-Agent', '').split('/')[0]  # Just browser name
            })
        
        return event_dict
    
    # Configure structlog with request context
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            configure_logger,  # Add our custom processor
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True)
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestContextManager:
    """Manages request-scoped context and correlation IDs."""
    
    @staticmethod
    def generate_request_id() -> str:
        """Generate a unique request ID."""
        return str(uuid.uuid4())[:8]
    
    @staticmethod
    def before_request():
        """Setup request context before handling request."""
        g.request_id = RequestContextManager.generate_request_id()
        g.request_start_time = datetime.now(timezone.utc)
        
        logger = structlog.get_logger("request")
        logger.info("Request started",
                   method=request.method,
                   path=request.path,
                   query_string=request.query_string.decode())
    
    @staticmethod
    def after_request(response):
        """Log request completion."""
        if hasattr(g, 'request_start_time'):
            duration = (datetime.now(timezone.utc) - g.request_start_time).total_seconds()
            
            logger = structlog.get_logger("request")
            logger.info("Request completed",
                       status_code=response.status_code,
                       duration_seconds=round(duration, 3),
                       content_length=response.content_length)
        
        return response


class ErrorHandler:
    """Enhanced error handling with structured logging."""
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize error handlers for Flask app."""
        app.errorhandler(400)(self.handle_bad_request)
        app.errorhandler(404)(self.handle_not_found)
        app.errorhandler(500)(self.handle_internal_error)
        app.errorhandler(Exception)(self.handle_exception)
    
    def handle_bad_request(self, error):
        """Handle 400 Bad Request errors."""
        return self._create_error_response(
            error_code="BAD_REQUEST",
            message="Invalid request",
            status_code=400,
            details={"description": str(error.description) if hasattr(error, 'description') else None}
        )
    
    def handle_not_found(self, error):
        """Handle 404 Not Found errors.""" 
        return self._create_error_response(
            error_code="NOT_FOUND",
            message="Resource not found",
            status_code=404,
            details={"path": request.path}
        )
    
    def handle_internal_error(self, error):
        """Handle 500 Internal Server errors."""
        logger = structlog.get_logger("error")
        logger.error("Internal server error",
                    error=str(error),
                    traceback=traceback.format_exc())
        
        return self._create_error_response(
            error_code="INTERNAL_ERROR",
            message="An internal error occurred",
            status_code=500
        )
    
    def handle_exception(self, error):
        """Handle uncaught exceptions."""
        logger = structlog.get_logger("error")
        logger.error("Uncaught exception",
                    error_type=type(error).__name__,
                    error=str(error),
                    traceback=traceback.format_exc())
        
        # Determine appropriate status code based on exception type
        if isinstance(error, (ValueError, TypeError)):
            status_code = 400
            error_code = "VALIDATION_ERROR"
        elif isinstance(error, PermissionError):
            status_code = 403
            error_code = "PERMISSION_ERROR"
        elif isinstance(error, FileNotFoundError):
            status_code = 404
            error_code = "FILE_NOT_FOUND"
        else:
            status_code = 500
            error_code = "UNEXPECTED_ERROR"
        
        return self._create_error_response(
            error_code=error_code,
            message=str(error),
            status_code=status_code,
            details={"error_type": type(error).__name__}
        )
    
    def _create_error_response(self, error_code: str, message: str, status_code: int, details: Optional[Dict] = None):
        """Create standardized error response."""
        from flask import jsonify
        
        response_data = {
            "error": {
                "code": error_code,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": getattr(g, 'request_id', None),
            }
        }
        
        if details:
            response_data["error"]["details"] = details
        
        return jsonify(response_data), status_code


def log_exceptions(logger_name: Optional[str] = None):
    """Decorator to log exceptions in functions."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = structlog.get_logger(logger_name or func.__name__)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error("Function execution failed",
                           function=func.__name__,
                           error_type=type(e).__name__,
                           error=str(e),
                           args_count=len(args),
                           kwargs_keys=list(kwargs.keys()))
                raise
        return wrapper
    return decorator


@contextmanager
def log_operation(operation_name: str, logger_name: Optional[str] = None, **context):
    """Context manager to log operation start/end with timing."""
    logger = structlog.get_logger(logger_name or "operation")
    start_time = datetime.now(timezone.utc)
    
    logger.info("Operation started",
               operation=operation_name,
               **context)
    
    try:
        yield
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info("Operation completed successfully",
                   operation=operation_name,
                   duration_seconds=round(duration, 3),
                   **context)
    except Exception as e:
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.error("Operation failed",
                    operation=operation_name,
                    duration_seconds=round(duration, 3),
                    error_type=type(e).__name__,
                    error=str(e),
                    **context)
        raise


class DatabaseErrorHandler:
    """Specialized error handler for database operations."""
    
    @staticmethod
    def handle_db_error(operation: str, error: Exception, **context):
        """Handle database-specific errors with appropriate logging."""
        logger = structlog.get_logger("database")
        
        if "database is locked" in str(error).lower():
            logger.warning("Database lock detected",
                         operation=operation,
                         error=str(error),
                         **context)
            raise DatabaseLockError("Database is temporarily locked") from error
            
        elif "no such table" in str(error).lower():
            logger.error("Database schema error",
                        operation=operation,
                        error=str(error),
                        **context)
            raise DatabaseSchemaError("Database table missing") from error
            
        elif "disk" in str(error).lower() and "full" in str(error).lower():
            logger.critical("Database disk full",
                           operation=operation,
                           error=str(error),
                           **context)
            raise DatabaseDiskFullError("Database disk is full") from error
        
        else:
            logger.error("Database operation failed",
                        operation=operation,
                        error_type=type(error).__name__,
                        error=str(error),
                        **context)
            raise DatabaseOperationError(f"Database operation failed: {error}") from error


class HueAPIErrorHandler:
    """Specialized error handler for Hue API operations."""
    
    @staticmethod
    def handle_api_error(endpoint: str, response, **context):
        """Handle Hue API errors with appropriate logging and exceptions."""
        logger = structlog.get_logger("hue_api")
        
        if response.status_code == 401:
            logger.error("Hue API authentication failed",
                        endpoint=endpoint,
                        status_code=response.status_code,
                        **context)
            raise HueAuthenticationError("Invalid or expired Hue app key")
            
        elif response.status_code == 403:
            logger.error("Hue API access forbidden",
                        endpoint=endpoint, 
                        status_code=response.status_code,
                        **context)
            raise HueAuthorizationError("Access to Hue bridge forbidden")
            
        elif response.status_code >= 500:
            logger.error("Hue API server error",
                        endpoint=endpoint,
                        status_code=response.status_code,
                        response_text=response.text[:500] if hasattr(response, 'text') else None,
                        **context)
            raise HueServerError("Hue bridge server error")
        
        else:
            logger.warning("Hue API unexpected response",
                          endpoint=endpoint,
                          status_code=response.status_code,
                          response_text=response.text[:200] if hasattr(response, 'text') else None,
                          **context)
            raise HueAPIError(f"Unexpected Hue API response: {response.status_code}")


# Custom exception classes
class HueEventLoggerError(Exception):
    """Base exception for Hue Event Logger."""
    pass


class DatabaseError(HueEventLoggerError):
    """Base class for database-related errors."""
    pass


class DatabaseLockError(DatabaseError):
    """Database is locked."""
    pass


class DatabaseSchemaError(DatabaseError):
    """Database schema issue."""
    pass


class DatabaseDiskFullError(DatabaseError):
    """Database disk full."""
    pass


class DatabaseOperationError(DatabaseError):
    """General database operation error."""
    pass


class HueAPIError(HueEventLoggerError):
    """Base class for Hue API errors.""" 
    pass


class HueAuthenticationError(HueAPIError):
    """Hue API authentication error."""
    pass


class HueAuthorizationError(HueAPIError):
    """Hue API authorization error."""
    pass


class HueServerError(HueAPIError):
    """Hue bridge server error."""
    pass