"""Hue event processing and streaming management."""
import json
import time
import queue
import threading
import datetime as dt
import requests
import structlog
from typing import Dict, Any, List
from database import HueDatabase
from config import config

logger = structlog.get_logger(__name__)


class HueEventProcessor:
    """Processes Hue bridge events and manages the event stream."""

    def __init__(self, bridge_ip: str, app_key: str, verify_tls: bool = False):
        self.bridge_ip = bridge_ip
        self.app_key = app_key
        self.verify_tls = verify_tls
        self.db = HueDatabase()

        # URLs
        self.event_url = f"https://{bridge_ip}/eventstream/clip/v2"
        self.devices_url = f"https://{bridge_ip}/clip/v2/resource/device"

        # Headers
        self.headers = {
            "hue-application-key": app_key,
            "Accept": "text/event-stream"
        }

        # State tracking
        self.bad_state_start = {}  # Track when devices went offline
        self.live_tail_events = queue.Queue(maxsize=config.event_queue_size)
        self.is_running = False
        self.stream_thread = None

    def start_event_stream(self):
        """Start the event streaming in a background thread."""
        if self.is_running:
            logger.warning("Event stream already running")
            return

        self.is_running = True
        self.stream_thread = threading.Thread(
            target=self._event_stream_loop,
            name="hue-event-stream",
            daemon=True
        )
        self.stream_thread.start()
        logger.info("Started Hue event stream")

    def stop_event_stream(self):
        """Stop the event streaming."""
        self.is_running = False
        if self.stream_thread and self.stream_thread.is_alive():
            self.stream_thread.join(timeout=5)
        logger.info("Stopped Hue event stream")

    def update_device_catalog(self):
        """Fetch and update the device catalog from the bridge."""
        try:
            logger.info("Updating device catalog")
            response = requests.get(
                self.devices_url,
                headers={"hue-application-key": self.app_key},
                verify=self.verify_tls,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            device_count = 0
            for item in data.get("data", []):
                rid = item.get("id")
                if not rid:
                    continue

                meta = item.get("metadata") or {}
                name = meta.get("name") or item.get("id_v1") or rid
                device_type = item.get("type", "device")

                self.db.upsert_device(rid, name, device_type)
                device_count += 1

            logger.info("Device catalog updated", device_count=device_count)

        except Exception as e:
            logger.error("Failed to update device catalog", error=str(e))

    def get_zigbee_connectivity(self):
        """Fetch zigbee connectivity information from the bridge."""
        try:
            zigbee_url = f"https://{self.bridge_ip}/clip/v2/resource/zigbee_connectivity"
            response = requests.get(
                zigbee_url,
                headers={"hue-application-key": self.app_key},
                verify=self.verify_tls,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            logger.debug("Fetched zigbee connectivity data",
                        device_count=len(data.get("data", [])))
            return data.get("data", [])

        except Exception as e:
            logger.error("Failed to fetch zigbee connectivity", error=str(e))
            return []

    def get_zgp_connectivity(self):
        """Fetch ZGP (Zigbee Green Power) connectivity information from the bridge."""
        try:
            zgp_url = f"https://{self.bridge_ip}/clip/v2/resource/zgp_connectivity"
            response = requests.get(
                zgp_url,
                headers={"hue-application-key": self.app_key},
                verify=self.verify_tls,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            logger.debug("Fetched ZGP connectivity data",
                        device_count=len(data.get("data", [])))
            return data.get("data", [])

        except Exception as e:
            logger.error("Failed to fetch ZGP connectivity", error=str(e))
            return []

    def _event_stream_loop(self):
        """Main event streaming loop."""
        # Update device catalog once at startup
        self.update_device_catalog()

        session = requests.Session()
        session.verify = self.verify_tls
        session.headers.update(self.headers)

        consecutive_errors = 0
        max_consecutive_errors = 10

        while self.is_running:
            try:
                logger.info("Connecting to Hue event stream")
                with session.get(self.event_url, stream=True, timeout=config.stream_timeout) as response:
                    response.raise_for_status()
                    consecutive_errors = 0  # Reset error counter on successful connection

                    for raw_line in response.iter_lines(decode_unicode=True):
                        if not self.is_running:
                            break

                        if not raw_line:
                            continue

                        line = raw_line.strip()
                        if not line.startswith("data:"):
                            continue

                        payload = line[5:].strip()
                        now_iso = dt.datetime.now(dt.UTC) .isoformat() + "Z"

                        try:
                            events = json.loads(payload)
                            if isinstance(events, list):
                                self._process_event_array(events, now_iso)
                        except json.JSONDecodeError as e:
                            logger.warning("Failed to parse event JSON", error=str(e))
                        except Exception as e:
                            logger.error("Error processing event", error=str(e))

            except requests.exceptions.RequestException as e:
                consecutive_errors += 1
                logger.error("Stream connection error",
                           error=str(e),
                           consecutive_errors=consecutive_errors)

                if consecutive_errors >= max_consecutive_errors:
                    logger.critical("Too many consecutive errors, stopping stream")
                    self.is_running = False
                    break

            except Exception as e:
                consecutive_errors += 1
                logger.error("Unexpected error in event stream",
                           error=str(e),
                           consecutive_errors=consecutive_errors)

            if self.is_running:
                logger.info("Reconnecting to event stream", delay=config.reconnect_delay)
                time.sleep(config.reconnect_delay)

    def _process_event_array(self, events: List[Dict[str, Any]], now_iso: str):
        """Process an array of events from the stream."""
        today = dt.date.today().isoformat()

        for event in events:
            event_type = event.get("type")
            data_list = event.get("data", [])

            for data in data_list:
                rid = data.get("id")
                if not rid:
                    continue

                dtype = data.get("type") or event_type

                # Store raw event
                self.db.insert_event(now_iso, rid, dtype, data)

                # Add to live tail queue
                try:
                    self.live_tail_events.put_nowait({
                        "ts": now_iso,
                        "rid": rid,
                        "rtype": dtype,
                        "raw": data
                    })
                except queue.Full:
                    # Drop oldest events if queue is full
                    try:
                        self.live_tail_events.get_nowait()
                        self.live_tail_events.put_nowait({
                            "ts": now_iso,
                            "rid": rid,
                            "rtype": dtype,
                            "raw": data
                        })
                    except queue.Empty:
                        pass

                # Update diagnostics
                self._update_device_diagnostics(rid, data, now_iso, today)

    def _update_device_diagnostics(self, rid: str, data: Dict[str, Any], now_iso: str, today: str):
        """Update device diagnostic information."""
        # Mark device as seen
        self.db.update_device_last_seen(rid, now_iso, today)

        # Check battery status
        self._check_battery_status(rid, data, today)

        # Check connectivity status
        self._check_connectivity_status(rid, data, today)

    def _check_battery_status(self, rid: str, data: Dict[str, Any], today: str):
        """Check and update battery status."""
        is_low = False

        # Check various battery state fields
        power_state = data.get("power_state") or data.get("battery_state")
        if isinstance(power_state, dict):
            state = power_state.get("battery_state")
            level = power_state.get("level")

            if state == "low":
                is_low = True
            elif isinstance(level, (int, float)) and level <= 10:
                is_low = True

        if is_low:
            self.db.set_battery_low(rid, today, is_low)

    def _check_connectivity_status(self, rid: str, data: Dict[str, Any], today: str):
        """Check and update connectivity status."""
        # Get status from various possible locations
        status = data.get("status")
        zigbee_conn = data.get("zigbee_connectivity")
        if isinstance(zigbee_conn, dict):
            status = zigbee_conn.get("status", status)

        if not status:
            return

        now_utc = dt.datetime.now(dt.UTC)

        if status in ("connectivity_issue", "disconnected"):
            # Device went offline - start tracking if not already
            if rid not in self.bad_state_start:
                self.bad_state_start[rid] = now_utc
                self.db.increment_disconnects(rid, today)
                logger.debug("Device disconnected", rid=rid, status=status)

        elif status == "connected":
            # Device came back online - calculate downtime
            start_time = self.bad_state_start.pop(rid, None)
            if start_time is not None:
                downtime_minutes = int((now_utc - start_time).total_seconds() // 60)
                if downtime_minutes > 0:
                    self.db.add_unreachable_minutes(rid, today, downtime_minutes)
                    logger.debug("Device reconnected",
                               rid=rid,
                               downtime_minutes=downtime_minutes)

    def get_live_events(self):
        """Generator for live events (for SSE streaming)."""
        while True:
            try:
                event = self.live_tail_events.get(timeout=1.0)
                yield event
            except queue.Empty:
                # Send keepalive
                yield {"type": "keepalive", "ts": dt.datetime.now(dt.UTC) .isoformat() + "Z"}

    def drain_live_events(self, max_events: int = 100) -> List[Dict[str, Any]]:
        """Drain events from the live queue."""
        events = []
        for _ in range(max_events):
            try:
                event = self.live_tail_events.get_nowait()
                events.append(event)
            except queue.Empty:
                break
        return events
