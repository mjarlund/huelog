"""Configuration management for Hue Event Logger."""
import os
from typing import Optional
from pydantic import BaseModel, Field, validator
import dotenv

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

    @validator('bridge_ip')
    def validate_bridge_ip(cls, v):
        if not v or v == "your-bridge-ip-here":
            raise ValueError("Please set a valid HUE_BRIDGE_IP")
        return v

    @validator('verify_tls', pre=True)
    def validate_verify_tls(cls, v):
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes', 'on')
        return bool(v)

    @classmethod
    def from_env(cls) -> 'Config':
        """Load configuration from environment variables."""
        try:
            return cls(
                bridge_ip=os.getenv("HUE_BRIDGE_IP", ""),
                app_key=os.getenv("HUE_APP_KEY"),
                verify_tls=os.getenv("HUE_VERIFY_TLS", "false"),
                db_path=os.getenv("DB_PATH", "./hue_events.sqlite"),
                host=os.getenv("FLASK_HOST", "0.0.0.0"),
                port=int(os.getenv("FLASK_PORT", "8080")),
                debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
            )
        except Exception as e:
            print(f"❌ Configuration error: {e}")
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
