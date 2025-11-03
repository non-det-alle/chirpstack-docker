import os
import sys

from src.redis_reader import RedisReader
from src.logs_formatter import LogsFormatter
from src.influxdb_writer import InfluxDBWriter
from src.logger import global_logger as logger
from src.config import settings


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "-c":
        file = os.path.basename(__file__)
        print(f"Usage: python {file} -c <path/to/config/dir>")
        return 1

    settings.load(sys.argv[2])
    logger.setLevel(settings.LOG_LEVEL)

    try:
        with InfluxDBWriter() as writer:
            with LogsFormatter(writer.write) as formatter:
                with RedisReader(formatter.format) as reader:
                    reader.read_forever()
    except KeyboardInterrupt:
        logger.info("Service interrupted. Shutting down...")


if __name__ == "__main__":
    sys.exit(main())
