import os
import sys
import asyncio

from .discovery_service import MQTTDiscoveryService
from .grpc_stream_reader import GRPCDeviceFrameReader
from .formatting import FrameToRecordFormatter
from .influxdb_writer import InfluxDBWriterAsync
from .config import settings
from .logger import logger


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "-c":
        file = os.path.basename(__file__).removesuffix(".py")
        print(f"Usage: python -m src.{file} -c <path/to/config/dir>")
        return 1

    settings.load(sys.argv[2])
    logger.setLevel(settings.LOG_LEVEL)

    async def run():
        async with InfluxDBWriterAsync() as writer:
            with FrameToRecordFormatter(writer.write) as formatter:
                async with GRPCDeviceFrameReader(formatter.format) as reader:
                    with MQTTDiscoveryService(reader.read_forever) as service:
                        await service.start()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Service interrupted. Shutting down...")


if __name__ == "__main__":
    sys.exit(main())
