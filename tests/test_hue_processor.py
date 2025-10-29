"""Unit tests for Hue event processor."""
import pytest
import json
import queue
import time
from datetime import datetime, timezone, date
from unittest.mock import Mock, patch, MagicMock

from hue_processor import HueEventProcessor


class TestHueEventProcessor:
    """Test class for HueEventProcessor operations."""

    @pytest.mark.unit
    def test_processor_initialization(self, temp_db):
        """Test event processor initialization."""
        processor = HueEventProcessor(
            bridge_ip="192.168.1.100",
            app_key="test-key",
            verify_tls=False
        )
        
        assert processor.bridge_ip == "192.168.1.100"
        assert processor.app_key == "test-key"
        assert processor.verify_tls is False
        assert processor.is_running is False
        assert isinstance(processor.live_tail_events, queue.Queue)

    @pytest.mark.unit
    def test_update_device_diagnostics_connectivity(self, mock_hue_processor):
        """Test device diagnostics update for connectivity events."""
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        today = date.today().isoformat()
        
        # Test device going offline
        offline_data = {
            "id": "test-device",
            "status": "connectivity_issue",
            "type": "zigbee_connectivity"
        }
        
        mock_hue_processor._update_device_diagnostics("test-device", offline_data, now_iso, today)
        
        # Verify disconnect was recorded
        health_data = mock_hue_processor.db.get_device_health(today)
        assert len(health_data) == 1
        assert health_data[0]["disconnects"] == 1

    @pytest.mark.unit
    def test_update_device_diagnostics_battery(self, mock_hue_processor):
        """Test device diagnostics update for battery events."""
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        today = date.today().isoformat()
        
        # Test low battery
        battery_data = {
            "id": "test-device",
            "type": "device_power",
            "power_state": {
                "battery_state": "low",
                "level": 5
            }
        }
        
        mock_hue_processor._update_device_diagnostics("test-device", battery_data, now_iso, today)
        
        # Verify battery low was recorded
        health_data = mock_hue_processor.db.get_device_health(today)
        assert len(health_data) == 1
        assert health_data[0]["battery_low"] == 1

    @pytest.mark.unit
    def test_update_device_diagnostics_battery_level(self, mock_hue_processor):
        """Test device diagnostics update for battery level."""
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        today = date.today().isoformat()
        
        # Test low battery by level
        battery_data = {
            "id": "test-device",
            "type": "device_power",
            "power_state": {
                "battery_state": "normal",
                "level": 8  # Below 10% threshold
            }
        }
        
        mock_hue_processor._update_device_diagnostics("test-device", battery_data, now_iso, today)
        
        # Verify battery low was recorded
        health_data = mock_hue_processor.db.get_device_health(today)
        assert len(health_data) == 1
        assert health_data[0]["battery_low"] == 1

    @pytest.mark.unit
    def test_connectivity_status_tracking(self, mock_hue_processor):
        """Test connectivity status tracking with downtime calculation."""
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        today = date.today().isoformat()
        
        # Simulate device going offline
        offline_data = {"id": "test-device", "status": "disconnected"}
        mock_hue_processor._update_device_diagnostics("test-device", offline_data, now_iso, today)
        
        # Verify device is tracked as offline
        assert "test-device" in mock_hue_processor.bad_state_start
        
        # Simulate device coming back online after some time
        # Mock time passing
        start_time = mock_hue_processor.bad_state_start["test-device"]
        future_time = datetime.now(timezone.utc)
        
        with patch('hue_processor.dt.datetime') as mock_dt:
            mock_dt.now.return_value = future_time
            
            online_data = {"id": "test-device", "status": "connected"}
            mock_hue_processor._update_device_diagnostics("test-device", online_data, now_iso, today)
        
        # Verify device is no longer tracked as offline
        assert "test-device" not in mock_hue_processor.bad_state_start

    @pytest.mark.unit
    def test_process_event_array(self, mock_hue_processor):
        """Test processing of event arrays."""
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        today = date.today().isoformat()
        
        events = [
            {
                "type": "update",
                "data": [
                    {
                        "id": "device1",
                        "type": "zigbee_connectivity",
                        "status": "connected"
                    },
                    {
                        "id": "device2",
                        "type": "device_power",
                        "power_state": {"battery_state": "normal"}
                    }
                ]
            }
        ]
        
        mock_hue_processor._process_event_array(events, now_iso)
        
        # Verify events were processed
        all_events = mock_hue_processor.db.get_events(limit=10)
        assert len(all_events) == 2
        
        # Verify devices were updated
        health_data = mock_hue_processor.db.get_device_health(today)
        assert len(health_data) == 2

    @pytest.mark.unit
    def test_live_events_queue_management(self, mock_hue_processor):
        """Test live events queue management."""
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        
        # Set a small queue size for testing
        mock_hue_processor.live_tail_events = queue.Queue(maxsize=2)
        
        events = [
            {
                "type": "update",
                "data": [
                    {"id": "device1", "type": "test1"},
                    {"id": "device2", "type": "test2"},
                    {"id": "device3", "type": "test3"}  # This should cause queue overflow
                ]
            }
        ]
        
        mock_hue_processor._process_event_array(events, now_iso)
        
        # Queue should have exactly 2 items (maxsize)
        assert mock_hue_processor.live_tail_events.qsize() == 2

    @pytest.mark.unit
    def test_drain_live_events(self, mock_hue_processor):
        """Test draining events from live queue."""
        # Add some events to the queue
        for i in range(5):
            event = {
                "ts": datetime.now(timezone.utc).isoformat() + "Z",
                "rid": f"device{i}",
                "rtype": "test",
                "raw": {"test": i}
            }
            mock_hue_processor.live_tail_events.put_nowait(event)
        
        # Drain 3 events
        drained = mock_hue_processor.drain_live_events(max_events=3)
        assert len(drained) == 3
        assert mock_hue_processor.live_tail_events.qsize() == 2
        
        # Drain remaining events
        remaining = mock_hue_processor.drain_live_events(max_events=10)
        assert len(remaining) == 2
        assert mock_hue_processor.live_tail_events.qsize() == 0

    @pytest.mark.unit
    @patch('hue_processor.requests.get')
    def test_update_device_catalog_success(self, mock_get, mock_hue_processor):
        """Test successful device catalog update."""
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "device1",
                    "type": "sensor",
                    "metadata": {"name": "Motion Sensor"}
                },
                {
                    "id": "device2",
                    "type": "light",
                    "metadata": {"name": "Living Room Light"}
                }
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        mock_hue_processor.update_device_catalog()
        
        # Verify devices were added to database
        device1 = mock_hue_processor.db.get_device_info("device1")
        device2 = mock_hue_processor.db.get_device_info("device2")
        
        assert device1["name"] == "Motion Sensor"
        assert device1["type"] == "sensor"
        assert device2["name"] == "Living Room Light"
        assert device2["type"] == "light"

    @pytest.mark.unit
    @patch('hue_processor.requests.get')
    def test_update_device_catalog_failure(self, mock_get, mock_hue_processor):
        """Test device catalog update failure handling."""
        # Mock API failure
        mock_get.side_effect = Exception("Connection failed")
        
        # Should not raise exception, just log error
        mock_hue_processor.update_device_catalog()

    @pytest.mark.unit
    @patch('hue_processor.requests.get')
    def test_get_zigbee_connectivity_success(self, mock_get, mock_hue_processor):
        """Test successful zigbee connectivity retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "zigbee1",
                    "status": "connected",
                    "channel": 20
                }
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        result = mock_hue_processor.get_zigbee_connectivity()
        
        assert len(result) == 1
        assert result[0]["id"] == "zigbee1"
        assert result[0]["status"] == "connected"

    @pytest.mark.unit
    @patch('hue_processor.requests.get')
    def test_get_zigbee_connectivity_failure(self, mock_get, mock_hue_processor):
        """Test zigbee connectivity retrieval failure."""
        mock_get.side_effect = Exception("Network error")
        
        result = mock_hue_processor.get_zigbee_connectivity()
        assert result == []

    @pytest.mark.unit
    @patch('hue_processor.requests.get')
    def test_get_zgp_connectivity_success(self, mock_get, mock_hue_processor):
        """Test successful ZGP connectivity retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "zgp1",
                    "status": "connected",
                    "source_id": 12345
                }
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        result = mock_hue_processor.get_zgp_connectivity()
        
        assert len(result) == 1
        assert result[0]["id"] == "zgp1"
        assert result[0]["status"] == "connected"

    @pytest.mark.unit
    def test_check_battery_status_various_formats(self, mock_hue_processor):
        """Test battery status checking with various data formats."""
        today = date.today().isoformat()
        
        test_cases = [
            # Case 1: battery_state field
            {
                "data": {"power_state": {"battery_state": "low"}},
                "expected_low": True
            },
            # Case 2: level field below threshold
            {
                "data": {"power_state": {"level": 5}},
                "expected_low": True
            },
            # Case 3: level field above threshold
            {
                "data": {"power_state": {"level": 50}},
                "expected_low": False
            },
            # Case 4: battery_state field in different location
            {
                "data": {"battery_state": {"battery_state": "low"}},
                "expected_low": True
            },
            # Case 5: no battery data
            {
                "data": {"status": "connected"},
                "expected_low": False
            }
        ]
        
        for i, case in enumerate(test_cases):
            device_id = f"test-device-{i}"
            mock_hue_processor._check_battery_status(device_id, case["data"], today)
            
            health_data = mock_hue_processor.db.get_device_health(today)
            device_health = next((d for d in health_data if d["rid"] == device_id), None)
            
            if case["expected_low"]:
                assert device_health is not None
                assert device_health["battery_low"] == 1
            # Note: If not expected to be low, either no record or battery_low = 0