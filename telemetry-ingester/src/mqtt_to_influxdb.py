import sys
import os

from .mqtt_event_reader import MQTTEventReader
from .formatting import EventToRecordsFormatter
from .influxdb_writer import InfluxDBWriter
from .config import settings
from .logger import logger


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
                with MQTTEventReader(formatter.format) as service:
                    service.loop_forever()

    try:
        run()
    except KeyboardInterrupt:
        logger.info("Service interrupted. Shutting down...")


if __name__ == "__main__":
    sys.exit(main())
