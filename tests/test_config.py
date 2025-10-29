"""Unit tests for configuration management."""
import pytest
import os
from unittest.mock import patch, Mock

from config import Config


class TestConfig:
    """Test class for Config operations."""

    @pytest.mark.unit
    def test_config_creation_with_minimal_required_fields(self):
        """Test config creation with only required fields."""
        config = Config(bridge_ip="192.168.1.100")
        
        assert config.bridge_ip == "192.168.1.100"
        assert config.app_key is None
        assert config.verify_tls is False
        assert config.db_path == "./hue_events.sqlite"
        assert config.host == "0.0.0.0"
        assert config.port == 8080
        assert config.debug is False

    @pytest.mark.unit
    def test_config_creation_with_all_fields(self):
        """Test config creation with all fields specified."""
        config = Config(
            bridge_ip="10.0.0.50",
            app_key="test-key-123",
            verify_tls=True,
            db_path="/tmp/test.sqlite",
            host="127.0.0.1",
            port=9000,
            debug=True,
            event_queue_size=5000,
            auth_timeout=60,
            stream_timeout=120,
            reconnect_delay=5
        )
        
        assert config.bridge_ip == "10.0.0.50"
        assert config.app_key == "test-key-123"
        assert config.verify_tls is True
        assert config.db_path == "/tmp/test.sqlite"
        assert config.host == "127.0.0.1"
        assert config.port == 9000
        assert config.debug is True
        assert config.event_queue_size == 5000
        assert config.auth_timeout == 60
        assert config.stream_timeout == 120
        assert config.reconnect_delay == 5

    @pytest.mark.unit
    @patch.dict(os.environ, {
        'HUE_BRIDGE_IP': '192.168.1.200',
        'HUE_APP_KEY': 'env-test-key',
        'HUE_VERIFY_TLS': 'true',
        'DB_PATH': '/env/test.sqlite',
        'FLASK_HOST': '0.0.0.0',
        'FLASK_PORT': '3000',
        'FLASK_DEBUG': 'true',
        'EVENT_QUEUE_SIZE': '2000',
        'AUTH_TIMEOUT': '45',
        'STREAM_TIMEOUT': '90',
        'RECONNECT_DELAY': '3'
    })
    def test_config_from_env_all_variables(self):
        """Test loading config from environment variables."""
        config = Config.from_env()
        
        assert config.bridge_ip == "192.168.1.200"
        assert config.app_key == "env-test-key"
        assert config.verify_tls is True
        assert config.db_path == "/env/test.sqlite"
        assert config.host == "0.0.0.0"
        assert config.port == 3000
        assert config.debug is True
        assert config.event_queue_size == 2000
        assert config.auth_timeout == 45
        assert config.stream_timeout == 90
        assert config.reconnect_delay == 3

    @pytest.mark.unit
    @patch.dict(os.environ, {
        'HUE_BRIDGE_IP': '10.1.1.1',
        'HUE_VERIFY_TLS': 'false',
        'FLASK_DEBUG': 'false'
    }, clear=True)
    def test_config_from_env_minimal_variables(self):
        """Test loading config with minimal environment variables."""
        config = Config.from_env()
        
        assert config.bridge_ip == "10.1.1.1"
        assert config.app_key is None  # Not set in env
        assert config.verify_tls is False
        assert config.debug is False
        # Other fields should have defaults
        assert config.db_path == "./hue_events.sqlite"
        assert config.host == "0.0.0.0"
        assert config.port == 8080

    @pytest.mark.unit
    @patch.dict(os.environ, {}, clear=True)
    def test_config_from_env_missing_required_field(self):
        """Test config creation fails when required field is missing."""
        with pytest.raises(Exception):  # Should raise validation error
            Config.from_env()

    @pytest.mark.unit
    @patch.dict(os.environ, {
        'HUE_BRIDGE_IP': '192.168.1.100',
        'FLASK_PORT': 'invalid_port'
    })
    def test_config_from_env_invalid_integer(self):
        """Test config creation fails with invalid integer values."""
        with pytest.raises(ValueError):
            Config.from_env()

    @pytest.mark.unit
    @patch.dict(os.environ, {
        'HUE_BRIDGE_IP': '192.168.1.100',
        'HUE_VERIFY_TLS': 'maybe',  # Invalid boolean
        'FLASK_DEBUG': 'yes'  # Invalid boolean
    })
    def test_config_boolean_conversion(self):
        """Test boolean conversion from environment variables."""
        config = Config.from_env()
        
        # Only 'true' (case-insensitive) should be True, everything else False
        assert config.verify_tls is False  # 'maybe' -> False
        assert config.debug is False  # 'yes' -> False

    @pytest.mark.unit
    @patch.dict(os.environ, {
        'HUE_BRIDGE_IP': '192.168.1.100',
        'HUE_VERIFY_TLS': 'TRUE',  # Test case insensitivity
        'FLASK_DEBUG': 'True'
    })
    def test_config_boolean_case_insensitive(self):
        """Test boolean conversion is case insensitive."""
        config = Config.from_env()
        
        assert config.verify_tls is True  # 'TRUE' -> True
        assert config.debug is True  # 'True' -> True

    @pytest.mark.unit
    def test_config_field_descriptions(self):
        """Test that config fields have proper descriptions."""
        # This tests the Pydantic model field definitions
        config = Config(bridge_ip="192.168.1.100")
        
        # Access field info through the model
        fields = config.model_fields
        
        assert "bridge_ip" in fields
        assert "app_key" in fields
        assert "verify_tls" in fields
        assert "db_path" in fields
        
        # Check that descriptions are present
        assert fields["bridge_ip"].description == "IP address of the Hue bridge"
        assert fields["app_key"].description == "Hue application key"

    @pytest.mark.unit
    def test_config_defaults(self):
        """Test that config defaults are set correctly."""
        config = Config(bridge_ip="192.168.1.100")
        
        # Test all default values
        assert config.app_key is None
        assert config.verify_tls is False
        assert config.db_path == "./hue_events.sqlite"
        assert config.host == "0.0.0.0"
        assert config.port == 8080
        assert config.debug is False
        assert config.event_queue_size == 10000
        assert config.auth_timeout == 30
        assert config.stream_timeout == 60
        assert config.reconnect_delay == 2