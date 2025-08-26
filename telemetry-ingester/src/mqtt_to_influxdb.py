import sys, time, os
import paho.mqtt.client as paho
from paho.mqtt.enums import CallbackAPIVersion

from src.unmarshaling import CHIRPSTACK_EVENTS, unmarshal_mqtt_event_to_dict
from src.formatter import format_event_data_to_records, MissingHandlerError
from src.influxdb_writer import InfluxDBWriter
from src.config import settings
from src.logger import logger


def _on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        logger.error(f"Failed to connect: {paho.connack_string(reason_code)}")
        return
    topics, qos = settings.MOSQUITTO_TOPICS, settings.MOSQUITTO_QOS
    logger.info(f'Connected to MQTT broker. Subscribing to "{topics}"')
    client.subscribe(topics, qos)


def _on_message(client, userdata, message):
    try:
        logger.debug(f'Received MQTT message for "{message.topic}"')
        event = message.topic.split("/")[-1]
        assert event in CHIRPSTACK_EVENTS  # otherwise update events module
        data = unmarshal_mqtt_event_to_dict(message.payload, event)
        logger.debug(f"Unmarshaled event data: {data}")
        try:
            records = format_event_data_to_records(data, event)
        except MissingHandlerError as e:
            logger.warning(f"Format handler not implemented for event {e}")
            return
        userdata["influxdb_write"](records)
    except Exception as e:
        logger.exception(f"Error processing MQTT message: {e}")


def _on_disconnect(client, userdata, flags, reason_code, properties):
    logger.info("Disconnected from MQTT broker.")
    if reason_code != 0:
        logger.warning("Unexpected disconnect. Reconnecting in 5s...")
        time.sleep(5)
        userdata["reconnect"]()


class MQTTToInfluxDB:
    def __init__(self):
        self.client = paho.Client(CallbackAPIVersion.VERSION2, clean_session=True)
        self.client.enable_logger(logger)
        self.influxdb = InfluxDBWriter()
        self._setup_callbacks()

    def _setup_callbacks(self):
        self.client.on_connect = _on_connect
        self.client.on_message = _on_message
        self.client.on_disconnect = _on_disconnect

        stateful = {"influxdb_write": self.influxdb.write, "reconnect": self.connect}
        self.client.user_data_set(stateful)

    def connect(self):
        hostname, port = settings.MOSQUITTO_HOSTNAME, settings.MOSQUITTO_PORT
        logger.info(f'Connecting to MQTT broker at "{hostname}:{port}"...')
        self.client.connect(hostname, port, keepalive=60)

    def loop_forever(self):
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            logger.info("Service interrupted. Shutting down...")
            self.client.disconnect()


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "-c":
        file = os.path.basename(__file__).removesuffix(".py")
        print(f"Usage: python -m src.{file} -c <path/to/config/dir>")
        return 1

    settings.load(sys.argv[2])
    logger.setLevel(settings.LOG_LEVEL)

    ingester = MQTTToInfluxDB()
    ingester.connect()
    ingester.loop_forever()


if __name__ == "__main__":
    sys.exit(main())
