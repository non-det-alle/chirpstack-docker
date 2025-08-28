import sys
import os

from src.mqtt_event_reader import MQTTEventReader
from src.formatting import EventToRecordsFormatter
from src.influxdb_writer import InfluxDBWriter
from src.config import settings
from src.logger import logger


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "-c":
        file = os.path.basename(__file__).removesuffix(".py")
        print(f"Usage: python -m src.{file} -c <path/to/config/dir>")
        return 1

    settings.load(sys.argv[2])
    logger.setLevel(settings.LOG_LEVEL)

    def run():
        with InfluxDBWriter() as writer:
            with EventToRecordsFormatter(writer.write) as formatter:
                with MQTTEventReader(formatter.format) as reader:
                    reader.loop_forever()

    try:
        run()
    except KeyboardInterrupt:
        logger.info("Service interrupted. Shutting down...")


if __name__ == "__main__":
    sys.exit(main())
