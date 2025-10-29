"""Configuration management for Hue Event Logger."""
import os
import ipaddress
from typing import Optional
from pathlib import Path

import dotenv
from pydantic import BaseModel, Field, field_validator, ConfigDict

dotenv.load_dotenv()


class Config(BaseModel):
    """Application configuration with validation."""
    
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra='forbid'
    )

    # Hue Bridge settings
    bridge_ip: str = Field(..., description="IP address of the Hue bridge")
    app_key: Optional[str] = Field(None, description="Hue application key", min_length=1)
    verify_tls: bool = Field(False, description="Verify TLS certificates")

    # Database settings
    db_path: str = Field("./hue_events.sqlite", description="SQLite database path")

    # Application settings
    host: str = Field("0.0.0.0", description="Flask host")
    port: int = Field(8080, description="Flask port", ge=1, le=65535)
    debug: bool = Field(False, description="Debug mode")

    # Event processing settings
    event_queue_size: int = Field(10000, description="Max events in live queue", ge=100, le=100000)
    auth_timeout: int = Field(30, description="Seconds to wait for button press", ge=5, le=300)
    stream_timeout: int = Field(60, description="Stream connection timeout", ge=10, le=600)
    reconnect_delay: int = Field(2, description="Delay between reconnection attempts", ge=1, le=60)

    # Logging settings
    log_level: str = Field("INFO", description="Logging level")
    log_file: Optional[str] = Field(None, description="Log file path")
    
    # Security settings
    api_key: Optional[str] = Field(None, description="API authentication key")
    
    # Performance settings
    max_db_connections: int = Field(10, description="Maximum database connections", ge=1, le=100)
    cache_ttl_seconds: int = Field(300, description="Cache TTL in seconds", ge=60, le=3600)
    
    @field_validator('bridge_ip')
    @classmethod
    def validate_ip_address(cls, v: str) -> str:
        """Validate IP address format."""
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            # Try to resolve hostname
            import socket
            try:
                resolved_ip = socket.gethostbyname(v)
                ipaddress.ip_address(resolved_ip)  # Validate resolved IP
                return v  # Return original hostname/FQDN
            except (socket.gaierror, ValueError):
                raise ValueError(f"Invalid IP address or hostname: {v}")
    
    @field_validator('db_path')
    @classmethod
    def validate_db_path(cls, v: str) -> str:
        """Validate database path."""
        path = Path(v)
        
        # Check if parent directory exists or can be created
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            raise ValueError(f"Cannot create database directory {path.parent}: {e}")
        
        # Check write permissions for parent directory
        if not os.access(path.parent, os.W_OK):
            raise ValueError(f"No write permission for database directory {path.parent}")
        
        return str(path.resolve())
    
    @field_validator('host')
    @classmethod  
    def validate_host(cls, v: str) -> str:
        """Validate host address."""
        if v in ("0.0.0.0", "127.0.0.1", "localhost"):
            return v
        
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            # Allow hostnames but validate format
            if not v.replace('-', '').replace('.', '').replace('_', '').isalnum():
                raise ValueError(f"Invalid host format: {v}")
            return v
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v_upper
    
    @field_validator('log_file')
    @classmethod
    def validate_log_file(cls, v: Optional[str]) -> Optional[str]:
        """Validate log file path."""
        if v is None:
            return v
        
        path = Path(v)
        try:
            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check write permissions
            if path.exists() and not os.access(path, os.W_OK):
                raise ValueError(f"No write permission for log file: {path}")
            elif not path.exists() and not os.access(path.parent, os.W_OK):
                raise ValueError(f"No write permission for log directory: {path.parent}")
                
        except (PermissionError, OSError) as e:
            raise ValueError(f"Invalid log file path {path}: {e}")
        
        return str(path.resolve())
    
    def get_database_url(self) -> str:
        """Get database URL for SQLAlchemy if needed."""
        return f"sqlite:///{self.db_path}"
    
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return not self.debug and self.log_level != "DEBUG"
    
    def validate_hue_config(self) -> list[str]:
        """Validate Hue-specific configuration and return warnings/errors."""
        issues = []
        
        if not self.app_key:
            issues.append("No Hue app key configured - authentication will be required")
        elif len(self.app_key) < 20:
            issues.append("Hue app key appears to be too short")
        
        if self.verify_tls and self.bridge_ip.startswith("192.168."):
            issues.append("TLS verification enabled for local network IP - may cause connection issues")
        
        if self.auth_timeout < 10:
            issues.append("Auth timeout is very short - users may not have enough time to press bridge button")
        
        return issues

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> 'Config':
        """Load configuration from environment variables with comprehensive validation."""
        if env_file:
            dotenv.load_dotenv(env_file)
        
        try:
            # Build config dict with environment variables
            config_data = cls._extract_env_vars()
            
            # Create and validate configuration
            config = cls(**config_data)
            
            # Run Hue-specific validation
            hue_issues = config.validate_hue_config()
            if hue_issues:
                print("⚠️  Configuration warnings:")
                for issue in hue_issues:
                    print(f"   - {issue}")
            
            return config

        except Exception as error:
            print(f"❌ Configuration error: {error}")
            cls._print_debug_info()
            raise

    @staticmethod
    def _extract_env_vars() -> dict:
        """Extract and validate environment variables."""
        config_data = {}
        
        # Mapping of env vars to config fields with type conversion
        env_mappings = {
            # Required fields
            "HUE_BRIDGE_IP": ("bridge_ip", str),
            
            # Optional string fields  
            "HUE_APP_KEY": ("app_key", str),
            "DB_PATH": ("db_path", str),
            "FLASK_HOST": ("host", str),
            "LOG_LEVEL": ("log_level", str),
            "LOG_FILE": ("log_file", str),
            "API_KEY": ("api_key", str),
            
            # Boolean fields
            "HUE_VERIFY_TLS": ("verify_tls", lambda x: x.lower() == "true"),
            "FLASK_DEBUG": ("debug", lambda x: x.lower() == "true"),
            
            # Integer fields
            "FLASK_PORT": ("port", int),
            "EVENT_QUEUE_SIZE": ("event_queue_size", int),
            "AUTH_TIMEOUT": ("auth_timeout", int),
            "STREAM_TIMEOUT": ("stream_timeout", int),
            "RECONNECT_DELAY": ("reconnect_delay", int),
            "MAX_DB_CONNECTIONS": ("max_db_connections", int),
            "CACHE_TTL_SECONDS": ("cache_ttl_seconds", int),
        }
        
        for env_var, (field_name, converter) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None and value.strip():
                try:
                    config_data[field_name] = converter(value)
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Invalid value for {env_var}: {value} ({e})")
        
        return config_data

    @staticmethod
    def _print_debug_info():
        """Print debug information for configuration issues."""
        print("📋 Current environment variables:")
        
        relevant_vars = [
            "HUE_BRIDGE_IP", "HUE_APP_KEY", "HUE_VERIFY_TLS", "DB_PATH",
            "FLASK_HOST", "FLASK_PORT", "FLASK_DEBUG", "LOG_LEVEL"
        ]
        
        for key in relevant_vars:
            value = os.getenv(key, "NOT SET")
            # Mask sensitive values
            if key in ("HUE_APP_KEY", "API_KEY") and value != "NOT SET":
                value = f"{value[:8]}..." if len(value) > 8 else "***"
            print(f"   {key}={value}")
    
    def to_dict(self) -> dict:
        """Convert config to dictionary, masking sensitive values."""
        data = self.model_dump()
        
        # Mask sensitive fields
        sensitive_fields = ["app_key", "api_key"]
        for field in sensitive_fields:
            if data.get(field):
                data[field] = f"{data[field][:8]}..." if len(data[field]) > 8 else "***"
        
        return data


# Global config instance
try:
    config = Config.from_env()
    print(f"✅ Configuration loaded successfully")
    print(f"   Bridge IP: {config.bridge_ip}")
    print(f"   Verify TLS: {config.verify_tls}")
    print(f"   Has APP Key: {'Yes' if config.app_key else 'No'}")
except Exception as e:
    print(f"❌ Failed to load configuration: {e}")
    raise
