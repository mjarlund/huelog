"""Hue Bridge authentication and connection management."""
import time
import requests
import structlog
from typing import Optional
from config import config

logger = structlog.get_logger(__name__)


class HueBridgeAuth:
    """Handles Hue Bridge authentication and key management."""

    def __init__(self, bridge_ip: str, verify_tls: bool = False):
        self.bridge_ip = bridge_ip
        self.verify_tls = verify_tls
        self.auth_url = f"https://{bridge_ip}/api"

    def generate_app_key(self) -> Optional[str]:
        """Generate a new APP key by prompting user to press the sync button."""
        logger.info("Starting Hue Bridge authentication", bridge_ip=self.bridge_ip)

        print(f"\n🔗 Attempting to connect to Hue Bridge at: {self.bridge_ip}")
        print("📝 No APP key found in environment variables.")
        print("\n⚠️  PLEASE PRESS THE SYNC BUTTON ON YOUR HUE BRIDGE NOW!")
        print(f"   (You have {config.auth_timeout} seconds to press it)")
        print("   The sync button is the round button on top of the bridge.")
        print("\n🔄 Waiting for sync button press...")

        payload = {
            "devicetype": "huelog#python_app",
            "generateclientkey": True
        }

        for attempt in range(config.auth_timeout):
            try:
                response = requests.post(
                    self.auth_url,
                    json=payload,
                    verify=self.verify_tls,
                    timeout=5
                )
                response.raise_for_status()
                data = response.json()

                if isinstance(data, list) and len(data) > 0:
                    result = data[0]

                    if "success" in result:
                        app_key = result["success"]["username"]
                        logger.info("Successfully generated APP key", key_preview=app_key[:8] + "...")
                        print(f"\n✅ SUCCESS! Generated APP key: {app_key}")

                        self._save_app_key_to_env(app_key)
                        return app_key

                    elif "error" in result:
                        error_type = result["error"].get("type", 0)
                        if error_type == 101:  # Button not pressed
                            remaining = config.auth_timeout - attempt
                            print(f"\r⏳ Waiting for sync button press... ({remaining}s remaining)",
                                  end="", flush=True)
                            time.sleep(1)
                            continue
                        else:
                            error_msg = result["error"].get("description", "Unknown error")
                            logger.error("Authentication error", error=error_msg, error_type=error_type)
                            print(f"\n❌ Error: {error_msg}")
                            break

            except requests.exceptions.RequestException as e:
                logger.error("Connection error during authentication", error=str(e))
                print(f"\n❌ Connection error: {e}")
                break
            except Exception as e:
                logger.error("Unexpected error during authentication", error=str(e))
                print(f"\n❌ Unexpected error: {e}")
                break

        logger.warning("Failed to generate APP key")
        print(f"\n❌ Failed to generate APP key. Please ensure:")
        print("   1. The bridge IP address is correct")
        print(f"   2. You pressed the sync button within {config.auth_timeout} seconds")
        print("   3. The bridge is accessible on your network")
        return None

    def _save_app_key_to_env(self, app_key: str) -> None:
        """Save the generated APP key to the .env file."""
        env_path = ".env"
        lines = []
        key_found = False

        try:
            with open(env_path, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            logger.info("Creating new .env file")

        # Update or add the HUE_APP_KEY line
        for i, line in enumerate(lines):
            if line.strip().startswith('HUE_APP_KEY='):
                lines[i] = f"HUE_APP_KEY={app_key}\n"
                key_found = True
                break

        if not key_found:
            lines.append(f"HUE_APP_KEY={app_key}\n")

        with open(env_path, 'w') as f:
            f.writelines(lines)

        logger.info("APP key saved to .env file")
        print(f"💾 APP key saved to {env_path}")

    def test_connection(self, app_key: str) -> bool:
        """Test if the app key works with the bridge."""
        try:
            test_url = f"https://{self.bridge_ip}/clip/v2/resource/device"
            response = requests.get(
                test_url,
                headers={"hue-application-key": app_key},
                verify=self.verify_tls,
                timeout=10
            )
            response.raise_for_status()
            logger.info("Bridge connection test successful")
            return True
        except Exception as e:
            logger.error("Bridge connection test failed", error=str(e))
            return False
