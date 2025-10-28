import asyncio
import time

import paho.mqtt.client as paho
from paho.mqtt.enums import CallbackAPIVersion

from .async_mqtt_client import ClientAsync
from .config import settings
from .logger import getLogger


class MQTTDiscoveryService:
    def __init__(self, on_discovery, log_level: None | str = None):
        self._endpoint = settings.MOSQUITTO_ENDPOINT
        self._topics = settings.MOSQUITTO_TOPICS
        self._reconnect_delay = settings.MOSQUITTO_RECONNECT_DELAY

        self._log = getLogger(self.__class__.__name__)
        self._log.setLevel(log_level if log_level else settings.LOG_LEVEL)

        self._client = ClientAsync(CallbackAPIVersion.VERSION2)
        self._on_discovery = on_discovery
        self._task_group: asyncio.TaskGroup
        self._main_task: asyncio.Task
        self._discovered = {}

        self._client.enable_logger(self._log)
        self._setup_callbacks()
        self._connect()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self):
        self._client.disconnect()

    def _setup_callbacks(self):
        def _on_connect(client, userdata, flags, rc, properties):
            if rc != 0:
                err = paho.connack_string(rc)
                self._log.error(f"Connection failure: {err}")
                return
            self._log.info(f"Connection success. Subscribing to {self._topics}")
            client.subscribe(self._topics)

        def _on_message(client, userdata, message):
            try:
                self._log.debug(f'MQTT message on topic "{message.topic}"')
                dev_eui = message.topic.split("/")[3]
                self._ensure_registered(dev_eui)
            except Exception as e:
                self._log.error(f"Error processing MQTT message: {e}")

        def _on_disconnect(client, userdata, flags, rc, properties):
            if rc != 0:
                err = paho.error_string(rc)
                self._log.error(f"Unexpected MQTT disconnect: {err} Reconnecting...")

        self._client.on_connect = _on_connect
        self._client.on_message = _on_message
        self._client.on_disconnect = _on_disconnect

    def _connect(self):
        hostname, port = self._endpoint.split(":")
        port = int(port)
        while True:
            try:
                self._log.info(f"Connecting to MQTT broker at {self._endpoint}")
                self._client.connect(hostname, port)
            except Exception as e:
                self._log.error(f"{e}. Retrying in {self._reconnect_delay}s...")
                time.sleep(self._reconnect_delay)
                continue
            break

    def _ensure_registered(self, id):
        def _unregister(_):
            self._log.info(f"Removing device {id}")
            self._discovered.pop(id, None)

        if id not in self._discovered:
            self._log.info(f"Registering device {id}")
            coroutine = self._on_discovery(id)
            task = self._task_group.create_task(coroutine)  # run concurrently
            task.add_done_callback(_unregister)
            self._discovered[id] = task

    async def start(self):
        async with asyncio.TaskGroup() as tg:
            self._task_group = tg
            coroutine = self._client.loop_forever_async()
            self._main_task = tg.create_task(coroutine)
