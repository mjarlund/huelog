"""Unit tests for Hue authentication."""
import pytest
import time
from unittest.mock import patch, Mock

from hue_auth import HueBridgeAuth


class TestHueBridgeAuth:
    """Test class for HueBridgeAuth operations."""

    @pytest.mark.unit
    def test_auth_initialization(self):
        """Test HueBridgeAuth initialization."""
        auth = HueBridgeAuth("192.168.1.100", verify_tls=True)
        
        assert auth.bridge_ip == "192.168.1.100"
        assert auth.verify_tls is True
        assert auth.auth_url == "https://192.168.1.100/api"

    @pytest.mark.unit
    @patch('hue_auth.requests.post')
    def test_generate_app_key_success(self, mock_post):
        """Test successful app key generation."""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "success": {
                    "username": "test-app-key-12345",
                    "clientkey": "test-client-key"
                }
            }
        ]
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        auth = HueBridgeAuth("192.168.1.100")
        
        with patch('builtins.print'), \
             patch('hue_auth.HueBridgeAuth._save_app_key_to_env'):
            
            result = auth.generate_app_key()
            
        assert result == "test-app-key-12345"
        
        # Verify request was made correctly
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://192.168.1.100/api"
        assert call_args[1]['json']['devicetype'] == "huelog#python_app"

    @pytest.mark.unit
    @patch('hue_auth.requests.post')
    def test_generate_app_key_button_not_pressed(self, mock_post):
        """Test app key generation when button not pressed."""
        # Mock button not pressed response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "error": {
                    "type": 101,
                    "description": "link button not pressed"
                }
            }
        ]
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        auth = HueBridgeAuth("192.168.1.100")
        
        with patch('builtins.print'), \
             patch('time.sleep'), \
             patch('hue_auth.config.auth_timeout', 2):  # Short timeout for test
            
            result = auth.generate_app_key()
            
        assert result is None

    @pytest.mark.unit
    @patch('hue_auth.requests.post')
    def test_generate_app_key_network_error(self, mock_post):
        """Test app key generation with network error."""
        mock_post.side_effect = Exception("Network unreachable")
        
        auth = HueBridgeAuth("192.168.1.100")
        
        with patch('builtins.print'):
            result = auth.generate_app_key()
            
        assert result is None

    @pytest.mark.unit
    @patch('hue_auth.requests.post')
    def test_generate_app_key_other_error(self, mock_post):
        """Test app key generation with other API error."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "error": {
                    "type": 999,
                    "description": "Some other error"
                }
            }
        ]
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        auth = HueBridgeAuth("192.168.1.100")
        
        with patch('builtins.print'):
            result = auth.generate_app_key()
            
        assert result is None

    @pytest.mark.unit
    @patch('hue_auth.requests.get')
    def test_test_connection_success(self, mock_get):
        """Test successful connection test."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        auth = HueBridgeAuth("192.168.1.100")
        result = auth.test_connection("test-app-key")
        
        assert result is True
        
        # Verify request was made correctly
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "hue-application-key" in call_args[1]['headers']
        assert call_args[1]['headers']['hue-application-key'] == "test-app-key"

    @pytest.mark.unit
    @patch('hue_auth.requests.get')
    def test_test_connection_failure(self, mock_get):
        """Test connection test failure."""
        mock_get.side_effect = Exception("Connection failed")
        
        auth = HueBridgeAuth("192.168.1.100")
        result = auth.test_connection("test-app-key")
        
        assert result is False

    @pytest.mark.unit
    @patch('builtins.open', create=True)
    @patch('os.path.exists')
    def test_save_app_key_to_env_new_file(self, mock_exists, mock_open):
        """Test saving app key to new .env file."""
        mock_exists.return_value = False
        
        # Mock file operations
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file
        
        with patch('builtins.print'):
            HueBridgeAuth._save_app_key_to_env("test-key-123")
        
        # Verify file was opened for writing
        assert mock_open.call_count == 2  # One for read (FileNotFoundError), one for write
        
        # Verify write was called with correct content
        write_calls = mock_file.write.call_args_list
        written_content = ''.join(call[0][0] for call in write_calls)
        assert "HUE_APP_KEY=test-key-123" in written_content

    @pytest.mark.unit
    @patch('builtins.open', create=True)
    def test_save_app_key_to_env_existing_file(self, mock_open):
        """Test saving app key to existing .env file."""
        # Mock existing file content
        existing_content = [
            "HUE_BRIDGE_IP=192.168.1.100\n",
            "HUE_APP_KEY=old-key\n",
            "DEBUG=true\n"
        ]
        
        # Mock file operations
        mock_file_read = Mock()
        mock_file_read.readlines.return_value = existing_content
        mock_file_write = Mock()
        
        mock_open.side_effect = [
            mock_file_read.__enter__.return_value,  # For reading
            mock_file_write.__enter__.return_value  # For writing
        ]
        
        with patch('builtins.print'):
            HueBridgeAuth._save_app_key_to_env("new-key-456")
        
        # Verify the key was updated
        write_calls = mock_file_write.writelines.call_args_list
        assert len(write_calls) == 1
        
        updated_lines = write_calls[0][0][0]
        assert "HUE_APP_KEY=new-key-456\n" in updated_lines
        assert "HUE_BRIDGE_IP=192.168.1.100\n" in updated_lines
        assert "DEBUG=true\n" in updated_lines