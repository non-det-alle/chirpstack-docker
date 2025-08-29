import asyncio

import paho.mqtt.client as paho
from paho.mqtt.enums import CallbackAPIVersion

from .async_mqtt_client import ClientAsync
from .unmarshaling import unmarshal_mqtt_event_to_dict
from .config import settings
from .logger import logger

# MQTT subscription topic(s)
# https://www.chirpstack.io/docs/chirpstack/integrations/mqtt.html
TOPICS = "application/#"


class MQTTDiscoveryService:
    def __init__(self, on_discovery):
        self._hostname = settings.MOSQUITTO_HOSTNAME
        self._port = settings.MOSQUITTO_PORT

        self._client = ClientAsync(CallbackAPIVersion.VERSION2)
        self._on_discovery = on_discovery
        self._task_group: asyncio.TaskGroup
        self._main_task: asyncio.Task
        self._discovered = {}

        self._setup_callbacks()
        self._client.enable_logger(logger)
        self._client.connect_async(self._hostname, self._port)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self):
        self._client.disconnect()

    def _setup_callbacks(self):
        def on_connect(client, userdata, flags, rc, properties):
            if rc != 0:
                err = paho.connack_string(rc)
                logger.error(f"Connection failure: {err}")
                return
            logger.info(f"Connection success. Subscribing to {TOPICS}")
            client.subscribe(TOPICS)

        def on_message(client, userdata, message):
            try:
                logger.debug(f'MQTT message on topic "{message.topic}"')
                event_type = message.topic.split("/")[-1]
                data = unmarshal_mqtt_event_to_dict(message.payload, event_type)
                logger.debug(f"Unmarshaled event data: {data}")
                dev_eui = data["device_info"]["dev_eui"]
                self._ensure_registered(dev_eui)
            except Exception as e:
                logger.exception(f"Error processing MQTT message: {e}")

        def on_disconnect(client, userdata, flags, rc, properties):
            if rc != 0:
                err = paho.error_string(rc)
                logger.error(f"Unexpected MQTT disconnect: {err} Reconnecting...")

        self._client.on_connect = on_connect
        self._client.on_message = on_message
        self._client.on_disconnect = on_disconnect

    def _ensure_registered(self, id):
        def unregister(_):
            logger.info(f"Removing device {id}")
            self._discovered.pop(id, None)

        if id not in self._discovered:
            logger.info(f"Registering device {id}")
            coroutine = self._on_discovery(id)
            task = self._task_group.create_task(coroutine)  # run concurrently
            task.add_done_callback(unregister)
            self._discovered[id] = task

    async def start(self):
        async with asyncio.TaskGroup() as tg:
            self._task_group = tg
            endpoint = f"{self._hostname}:{self._port}"
            logger.info(f"Connecting to MQTT broker at {endpoint}")
            coroutine = self._client.loop_forever_async()
            self.main_task = tg.create_task(coroutine)
