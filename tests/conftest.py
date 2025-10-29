"""Test fixtures and utilities for Hue Event Logger tests."""
import pytest
import tempfile
import os
import json
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock

# Local imports
from database import HueDatabase
from hue_processor import HueEventProcessor
from config import Config


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    
    db = HueDatabase(db_path=path)
    yield db
    
    # Cleanup
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return Config(
        bridge_ip="192.168.1.100",
        app_key="test-app-key-123",
        verify_tls=False,
        db_path=":memory:",
        host="127.0.0.1",
        port=8080,
        debug=True,
        event_queue_size=100,
        auth_timeout=10,
        stream_timeout=30,
        reconnect_delay=1
    )


@pytest.fixture
def sample_hue_event():
    """Sample Hue bridge event for testing."""
    return {
        "id": "test-device-123",
        "type": "zigbee_connectivity",
        "status": "connected",
        "owner": {
            "rid": "owner-123",
            "rtype": "device"
        },
        "metadata": {
            "name": "Motion Sensor",
            "archetype": "motion_sensor"
        }
    }


@pytest.fixture
def sample_battery_event():
    """Sample battery event for testing."""
    return {
        "id": "battery-device-456",
        "type": "device_power",
        "power_state": {
            "battery_state": "low",
            "level": 5
        },
        "metadata": {
            "name": "Dimmer Switch",
            "archetype": "dimmer_switch"
        }
    }


@pytest.fixture
def mock_hue_processor(mock_config):
    """Create a mock Hue event processor for testing."""
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as tmp:
        db_path = tmp.name
    
    processor = HueEventProcessor(
        bridge_ip=mock_config.bridge_ip,
        app_key=mock_config.app_key,
        verify_tls=mock_config.verify_tls
    )
    processor.db = HueDatabase(db_path=db_path)
    
    yield processor
    
    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def mock_requests_response():
    """Mock requests response for testing."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.ok = True
    mock_response.json.return_value = {
        "data": [
            {
                "id": "test-device-1",
                "type": "device",
                "metadata": {
                    "name": "Test Device 1"
                }
            }
        ]
    }
    return mock_response


@pytest.fixture
def flask_test_client(mock_config):
    """Create a Flask test client."""
    # Mock the config module
    import app
    original_config = app.config
    app.config = mock_config
    
    # Create test app
    test_app = app.create_app()
    test_app.config['TESTING'] = True
    
    with test_app.test_client() as client:
        with test_app.app_context():
            yield client
    
    # Restore original config
    app.config = original_config


class MockEventStream:
    """Mock event stream for testing SSE functionality."""
    
    def __init__(self, events=None):
        self.events = events or []
        self.index = 0
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self.index >= len(self.events):
            raise StopIteration
        
        event = self.events[self.index]
        self.index += 1
        
        # Format as SSE
        return f"data: {json.dumps(event)}"


@pytest.fixture
def mock_event_stream():
    """Create a mock event stream."""
    events = [
        {
            "type": "device",
            "data": [{
                "id": "test-1",
                "type": "zigbee_connectivity",
                "status": "connected"
            }]
        },
        {
            "type": "battery",
            "data": [{
                "id": "test-2",
                "type": "device_power",
                "power_state": {"battery_state": "normal"}
            }]
        }
    ]
    return MockEventStream(events)


def create_test_event(rid="test-device", event_type="zigbee_connectivity", status="connected", **kwargs):
    """Helper function to create test events."""
    base_event = {
        "id": rid,
        "type": event_type,
        "status": status,
        "metadata": {
            "name": f"Test Device {rid[-3:]}",
            "archetype": "sensor"
        }
    }
    base_event.update(kwargs)
    return base_event


def create_test_device_data(rid="test-device", name="Test Device", device_type="sensor"):
    """Helper function to create test device data."""
    return {
        "id": rid,
        "type": device_type,
        "metadata": {
            "name": name,
            "archetype": device_type
        }
    }


@pytest.fixture
def iso_timestamp():
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat() + "Z"


@pytest.fixture
def iso_date():
    """Get current date in ISO format."""
    return datetime.now(timezone.utc).date().isoformat()