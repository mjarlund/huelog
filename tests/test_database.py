"""Unit tests for database operations."""
import pytest
import json
from datetime import datetime, timezone, date, timedelta

from database import HueDatabase


class TestHueDatabase:
    """Test class for HueDatabase operations."""

    @pytest.mark.unit
    def test_database_initialization(self, temp_db):
        """Test database initialization creates required tables."""
        with temp_db.get_connection() as conn:
            cur = conn.cursor()
            
            # Check tables exist
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}
            
            expected_tables = {'events', 'devices', 'diag'}
            assert expected_tables.issubset(tables)
            
            # Check indexes exist
            cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cur.fetchall() if not row[0].startswith('sqlite_autoindex')}
            
            expected_indexes = {
                'idx_events_ts', 
                'idx_events_rid', 
                'idx_events_rtype', 
                'idx_diag_day'
            }
            assert expected_indexes.issubset(indexes)

    @pytest.mark.unit
    def test_insert_and_get_events(self, temp_db, iso_timestamp):
        """Test event insertion and retrieval."""
        # Insert test event
        test_data = {"status": "connected", "type": "zigbee_connectivity"}
        temp_db.insert_event(iso_timestamp, "test-device", "connectivity", test_data)
        
        # Retrieve events
        events = temp_db.get_events()
        assert len(events) == 1
        
        event = events[0]
        assert event["rid"] == "test-device"
        assert event["rtype"] == "connectivity"
        assert json.loads(event["raw"]) == test_data

    @pytest.mark.unit
    def test_get_events_with_filter(self, temp_db, iso_timestamp):
        """Test event retrieval with filtering."""
        # Insert multiple events
        events_data = [
            ("device1", "motion", {"type": "motion", "motion": True}),
            ("device2", "battery", {"type": "battery", "level": 50}),
            ("device1", "connectivity", {"type": "zigbee_connectivity", "status": "connected"})
        ]
        
        for rid, rtype, data in events_data:
            temp_db.insert_event(iso_timestamp, rid, rtype, data)
        
        # Test filtering by device ID
        device1_events = temp_db.get_events("device1")
        assert len(device1_events) == 2
        
        # Test filtering by event type
        motion_events = temp_db.get_events("motion")
        assert len(motion_events) == 1
        assert json.loads(motion_events[0]["raw"])["motion"] is True
        
        # Test filtering by content
        battery_events = temp_db.get_events("battery")
        assert len(battery_events) == 1

    @pytest.mark.unit
    def test_upsert_device(self, temp_db):
        """Test device upsert operations."""
        # Insert new device
        temp_db.upsert_device("dev1", "Motion Sensor", "sensor")
        
        # Verify insert
        device = temp_db.get_device_info("dev1")
        assert device["name"] == "Motion Sensor"
        assert device["type"] == "sensor"
        
        # Update existing device
        temp_db.upsert_device("dev1", "Updated Motion Sensor", "motion_sensor")
        
        # Verify update
        device = temp_db.get_device_info("dev1")
        assert device["name"] == "Updated Motion Sensor"
        assert device["type"] == "motion_sensor"

    @pytest.mark.unit
    def test_device_diagnostics(self, temp_db, iso_timestamp, iso_date):
        """Test device diagnostics operations."""
        device_rid = "test-device"
        
        # Test last seen update
        temp_db.update_device_last_seen(device_rid, iso_timestamp, iso_date)
        
        # Test disconnect increment
        temp_db.increment_disconnects(device_rid, iso_date)
        temp_db.increment_disconnects(device_rid, iso_date)
        
        # Test unreachable minutes
        temp_db.add_unreachable_minutes(device_rid, iso_date, 45)
        temp_db.add_unreachable_minutes(device_rid, iso_date, 15)
        
        # Test battery low
        temp_db.set_battery_low(device_rid, iso_date, True)
        
        # Verify health data
        health_data = temp_db.get_device_health(iso_date)
        assert len(health_data) == 1
        
        device_health = health_data[0]
        assert device_health["rid"] == device_rid
        assert device_health["disconnects"] == 2
        assert device_health["minutes_unreachable"] == 60
        assert device_health["battery_low"] == 1
        assert device_health["last_seen_ts"] == iso_timestamp

    @pytest.mark.unit
    def test_get_device_health_date_filtering(self, temp_db, iso_timestamp):
        """Test device health date filtering."""
        device_rid = "test-device"
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        
        # Add data for different days
        temp_db.increment_disconnects(device_rid, today)
        temp_db.increment_disconnects(device_rid, yesterday)
        
        # Get health data from today only
        health_data = temp_db.get_device_health(today)
        assert len(health_data) == 1
        assert health_data[0]["disconnects"] == 1
        
        # Get health data from yesterday onwards
        health_data = temp_db.get_device_health(yesterday)
        assert len(health_data) == 1
        assert health_data[0]["disconnects"] == 2  # Sum of both days

    @pytest.mark.unit
    def test_get_events_since_id(self, temp_db, iso_timestamp):
        """Test getting events since a specific ID."""
        # Insert multiple events
        for i in range(5):
            temp_db.insert_event(iso_timestamp, f"device{i}", "test", {"index": i})
        
        # Get max ID (should be 5)
        max_id = temp_db.get_max_event_id()
        assert max_id == 5
        
        # Get events since ID 3
        events = temp_db.get_events_since_id(3)
        assert len(events) == 2  # Events 4 and 5
        assert events[0][0] == 4  # First column is ID
        assert events[1][0] == 5

    @pytest.mark.unit
    def test_add_zero_unreachable_minutes(self, temp_db, iso_date):
        """Test that zero or negative unreachable minutes are ignored."""
        device_rid = "test-device"
        
        # These should be ignored
        temp_db.add_unreachable_minutes(device_rid, iso_date, 0)
        temp_db.add_unreachable_minutes(device_rid, iso_date, -5)
        
        # This should be recorded
        temp_db.add_unreachable_minutes(device_rid, iso_date, 10)
        
        health_data = temp_db.get_device_health(iso_date)
        assert len(health_data) == 1
        assert health_data[0]["minutes_unreachable"] == 10

    @pytest.mark.unit
    def test_set_battery_low_false_ignored(self, temp_db, iso_date):
        """Test that setting battery_low to False is ignored."""
        device_rid = "test-device"
        
        # This should be ignored
        temp_db.set_battery_low(device_rid, iso_date, False)
        
        health_data = temp_db.get_device_health(iso_date)
        if health_data:
            # If record exists, battery_low should be 0 (default)
            assert health_data[0]["battery_low"] == 0
        else:
            # No record should be created for False battery_low
            assert len(health_data) == 0

    @pytest.mark.unit
    def test_database_connection_context_manager(self, temp_db):
        """Test that the database connection context manager works correctly."""
        # Test successful connection
        with temp_db.get_connection() as conn:
            assert conn is not None
            cur = conn.cursor()
            cur.execute("SELECT 1")
            result = cur.fetchone()
            assert result[0] == 1
        
        # Connection should be closed after context
        # Note: Can't directly test if connection is closed in SQLite

    @pytest.mark.unit
    def test_cleanup_old_events(self, temp_db, iso_timestamp):
        """Test cleanup of old events."""
        # Insert some events
        for i in range(10):
            temp_db.insert_event(iso_timestamp, f"device{i}", "test", {"index": i})
        
        # Verify events exist
        events = temp_db.get_events(limit=100)
        assert len(events) == 10
        
        # Cleanup events (with default 30 days, nothing should be deleted in test)
        deleted_count = temp_db.cleanup_old_events(days_to_keep=30)
        assert deleted_count == 0  # Events just created, shouldn't be deleted
        
        # Verify events still exist
        events = temp_db.get_events(limit=100)
        assert len(events) == 10