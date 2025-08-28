import paho.mqtt.client as paho
from paho.mqtt.enums import CallbackAPIVersion

from .unmarshaling import unmarshal_mqtt_event_to_dict
from .config import settings
from .logger import logger


class MQTTEventReader:
    def __init__(self, on_read):
        self._hostname = settings.MOSQUITTO_HOSTNAME
        self._port = settings.MOSQUITTO_PORT
        self._topics = settings.MOSQUITTO_TOPICS
        self._qos = settings.MOSQUITTO_QOS

        self._client = paho.Client(CallbackAPIVersion.VERSION2)
        self._on_read = on_read

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
            logger.info(f"Connection success. Subscribing to {self._topics}")
            client.subscribe(self._topics, self._qos)

        def on_message(client, userdata, message):
            try:
                logger.debug(f"MQTT message on topic {message.topic}")
                event_type = message.topic.split("/")[-1]
                event = unmarshal_mqtt_event_to_dict(message.payload, event_type)
                logger.debug(f"Unmarshaled event data: {event}")
                self._on_read(event, event_type)
            except Exception as e:
                logger.error(f"Error processing MQTT message: {e}")

        def on_disconnect(client, userdata, flags, rc, properties):
            if rc != 0:
                err = paho.error_string(rc)
                logger.error(f"Unexpected MQTT disconnect: {err} Reconnecting...")

        self._client.on_connect = on_connect
        self._client.on_message = on_message
        self._client.on_disconnect = on_disconnect

    def loop_forever(self):
        endpoint = f"{self._hostname}:{self._port}"
        logger.info(f"Connecting to MQTT broker at {endpoint}")
        self._client.loop_forever()
