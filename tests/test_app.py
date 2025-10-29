"""Integration tests for Flask application."""
import pytest
import json
from unittest.mock import patch, Mock

import app


class TestFlaskApp:
    """Test class for Flask application routes and functionality."""

    @pytest.mark.integration
    def test_index_route_no_events(self, flask_test_client):
        """Test index route with no events."""
        with patch.object(app, 'db') as mock_db:
            mock_db.get_events.return_value = []
            
            response = flask_test_client.get('/')
            assert response.status_code == 200
            assert b'No events recorded yet' in response.data

    @pytest.mark.integration
    def test_index_route_with_events(self, flask_test_client):
        """Test index route with events."""
        # Mock events data
        mock_events = [
            {
                'ts': '2023-10-01T12:00:00Z',
                'rid': 'test-device-1',
                'rtype': 'zigbee_connectivity', 
                'raw': '{"status": "connected"}'
            }
        ]
        
        with patch.object(app, 'db') as mock_db:
            mock_db.get_events.return_value = mock_events
            
            response = flask_test_client.get('/')
            assert response.status_code == 200
            assert b'test-device-1' in response.data
            assert b'zigbee_connectivity' in response.data

    @pytest.mark.integration
    def test_index_route_with_filter(self, flask_test_client):
        """Test index route with query filter."""
        with patch.object(app, 'db') as mock_db:
            mock_db.get_events.return_value = []
            
            response = flask_test_client.get('/?q=motion&limit=100')
            assert response.status_code == 200
            
            # Verify db.get_events was called with correct parameters
            mock_db.get_events.assert_called_once_with('motion', 100)

    @pytest.mark.integration
    def test_health_route_no_devices(self, flask_test_client):
        """Test health route with no devices."""
        with patch.object(app, 'db') as mock_db:
            mock_db.get_device_health.return_value = []
            
            response = flask_test_client.get('/health')
            assert response.status_code == 200
            assert b'No device data available' in response.data

    @pytest.mark.integration  
    def test_health_route_with_devices(self, flask_test_client):
        """Test health route with device data."""
        # Mock device health data
        mock_health_data = [
            {
                'rid': 'device-1',
                'name': 'Motion Sensor',
                'type': 'sensor',
                'disconnects': 2,
                'minutes_unreachable': 45,
                'last_seen_ts': '2023-10-01T12:00:00Z',
                'battery_low': 0
            }
        ]
        
        with patch.object(app, 'db') as mock_db:
            mock_db.get_device_health.return_value = mock_health_data
            
            response = flask_test_client.get('/health')
            assert response.status_code == 200
            assert b'Motion Sensor' in response.data
            assert b'device-1' in response.data

    @pytest.mark.integration
    def test_health_route_with_custom_date(self, flask_test_client):
        """Test health route with custom since date."""
        with patch.object(app, 'db') as mock_db:
            mock_db.get_device_health.return_value = []
            
            response = flask_test_client.get('/health?since=2023-10-01')
            assert response.status_code == 200
            
            # Verify db was called with correct date
            mock_db.get_device_health.assert_called_once_with('2023-10-01')

    @pytest.mark.integration
    def test_api_stats_success(self, flask_test_client):
        """Test API stats endpoint success."""
        with patch.object(app, 'db') as mock_db:
            # Mock database connection and cursor
            mock_conn = Mock()
            mock_cur = Mock()
            mock_conn.cursor.return_value = mock_cur
            mock_db.get_connection.return_value.__enter__.return_value = mock_conn
            
            # Mock query results
            mock_cur.fetchone.side_effect = [
                [1000],  # total_events
                [25],    # total_devices  
                [20],    # active_devices_7d
                [15]     # events_last_hour
            ]
            
            response = flask_test_client.get('/api/stats')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data['total_events'] == 1000
            assert data['total_devices'] == 25
            assert data['active_devices_7d'] == 20
            assert data['events_last_hour'] == 15
            assert 'bridge_ip' in data

    @pytest.mark.integration
    def test_api_stats_database_error(self, flask_test_client):
        """Test API stats endpoint with database error."""
        with patch.object(app, 'db') as mock_db:
            mock_db.get_connection.side_effect = Exception("Database error")
            
            response = flask_test_client.get('/api/stats')
            assert response.status_code == 500
            
            data = json.loads(response.data)
            assert 'error' in data

    @pytest.mark.integration
    def test_api_refresh_devices_success(self, flask_test_client):
        """Test API refresh devices endpoint success."""
        with patch.object(app, 'event_processor') as mock_processor:
            response = flask_test_client.get('/api/refresh-devices')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data['status'] == 'success'
            
            # Verify update_device_catalog was called
            mock_processor.update_device_catalog.assert_called_once()

    @pytest.mark.integration
    def test_api_refresh_devices_no_processor(self, flask_test_client):
        """Test API refresh devices when processor not initialized."""
        with patch.object(app, 'event_processor', None):
            response = flask_test_client.get('/api/refresh-devices')
            assert response.status_code == 503
            
            data = json.loads(response.data)
            assert 'error' in data

    @pytest.mark.integration
    def test_zigbee_connectivity_success(self, flask_test_client):
        """Test zigbee connectivity endpoint success."""
        mock_connectivity_data = [
            {
                'id': 'zigbee-1',
                'status': 'connected',
                'channel': 20
            }
        ]
        
        with patch.object(app, 'event_processor') as mock_processor, \
             patch.object(app, 'db') as mock_db:
            
            mock_processor.get_zigbee_connectivity.return_value = mock_connectivity_data
            mock_db.get_device_info.return_value = {
                'name': 'Test Device',
                'type': 'sensor'
            }
            
            response = flask_test_client.get('/resource/zigbee_connectivity')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert len(data['data']) == 1
            assert data['data'][0]['device_name'] == 'Test Device'
            assert data['data'][0]['device_type'] == 'sensor'
            assert data['count'] == 1

    @pytest.mark.integration
    def test_zgp_connectivity_success(self, flask_test_client):
        """Test ZGP connectivity endpoint success."""
        mock_connectivity_data = [
            {
                'id': 'zgp-1',
                'status': 'connected',
                'source_id': 12345
            }
        ]
        
        with patch.object(app, 'event_processor') as mock_processor, \
             patch.object(app, 'db') as mock_db:
            
            mock_processor.get_zgp_connectivity.return_value = mock_connectivity_data
            mock_db.get_device_info.return_value = None  # Device not in database
            
            response = flask_test_client.get('/resource/zgp_connectivity')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert len(data['data']) == 1
            assert data['data'][0]['device_name'] == 'zgp-1'  # Falls back to ID
            assert data['data'][0]['device_type'] == 'unknown'
            assert data['protocol'] == 'zgp'

    @pytest.mark.integration
    def test_tail_route_no_processor(self, flask_test_client):
        """Test tail route when event processor is not available."""
        with patch.object(app, 'event_processor', None):
            response = flask_test_client.get('/tail')
            assert response.status_code == 200
            assert response.mimetype == 'text/event-stream'

    @pytest.mark.integration
    def test_error_handlers(self, flask_test_client):
        """Test error handlers."""
        # Test 404
        response = flask_test_client.get('/nonexistent-route')
        assert response.status_code == 404
        
        data = json.loads(response.data)
        assert data['error'] == 'Not found'

    @pytest.mark.integration
    def test_index_route_database_error(self, flask_test_client):
        """Test index route handles database errors gracefully."""
        with patch.object(app, 'db') as mock_db:
            mock_db.get_events.side_effect = Exception("Database connection failed")
            
            response = flask_test_client.get('/')
            assert response.status_code == 200
            assert b'Database connection failed' in response.data

    @pytest.mark.integration
    def test_health_route_database_error(self, flask_test_client):
        """Test health route handles database errors gracefully."""
        with patch.object(app, 'db') as mock_db:
            mock_db.get_device_health.side_effect = Exception("Database query failed")
            
            response = flask_test_client.get('/health')
            assert response.status_code == 200
            assert b'Database query failed' in response.data