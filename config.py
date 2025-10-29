"""Configuration management for Hue Event Logger."""
import os
from typing import Optional

import dotenv
from pydantic import BaseModel, Field

dotenv.load_dotenv()


class Config(BaseModel):
    """Application configuration with validation."""

    # Hue Bridge settings
    bridge_ip: str = Field(..., description="IP address of the Hue bridge")
    app_key: Optional[str] = Field(None, description="Hue application key")
    verify_tls: bool = Field(False, description="Verify TLS certificates")

    # Database settings
    db_path: str = Field("./hue_events.sqlite", description="SQLite database path")

    # Application settings
    host: str = Field("0.0.0.0", description="Flask host")
    port: int = Field(8080, description="Flask port")
    debug: bool = Field(False, description="Debug mode")

    # Event processing settings
    event_queue_size: int = Field(10000, description="Max events in live queue")
    auth_timeout: int = Field(30, description="Seconds to wait for button press")
    stream_timeout: int = Field(60, description="Stream connection timeout")
    reconnect_delay: int = Field(2, description="Delay between reconnection attempts")

    @classmethod
    def from_env(cls) -> 'Config':
        """Load configuration from environment variables."""
        try:
            # Build config dict with only non-None values
            config_data = {}

            # Required field
            bridge_ip = os.getenv("HUE_BRIDGE_IP")
            if bridge_ip:
                config_data["bridge_ip"] = bridge_ip

            # Optional string fields
            app_key = os.getenv("HUE_APP_KEY")
            if app_key:
                config_data["app_key"] = app_key

            db_path = os.getenv("DB_PATH")
            if db_path:
                config_data["db_path"] = db_path

            host = os.getenv("FLASK_HOST")
            if host:
                config_data["host"] = host

            # Boolean fields with custom conversion
            verify_tls = os.getenv("HUE_VERIFY_TLS")
            if verify_tls is not None:
                config_data["verify_tls"] = verify_tls.lower() == "true"

            debug = os.getenv("FLASK_DEBUG")
            if debug is not None:
                config_data["debug"] = debug.lower() == "true"

            # Integer fields
            port = os.getenv("FLASK_PORT")
            if port:
                config_data["port"] = int(port)

            event_queue_size = os.getenv("EVENT_QUEUE_SIZE")
            if event_queue_size:
                config_data["event_queue_size"] = int(event_queue_size)

            auth_timeout = os.getenv("AUTH_TIMEOUT")
            if auth_timeout:
                config_data["auth_timeout"] = int(auth_timeout)

            stream_timeout = os.getenv("STREAM_TIMEOUT")
            if stream_timeout:
                config_data["stream_timeout"] = int(stream_timeout)

            reconnect_delay = os.getenv("RECONNECT_DELAY")
            if reconnect_delay:
                config_data["reconnect_delay"] = int(reconnect_delay)

            return cls(**config_data)

        except Exception as error:
            print(f"❌ Configuration error: {error}")
            print("📋 Current environment variables:")
            for key in ["HUE_BRIDGE_IP", "HUE_APP_KEY", "HUE_VERIFY_TLS", "DB_PATH"]:
                value = os.getenv(key, "NOT SET")
                print(f"   {key}={value}")
            raise


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
