import os
import sys
import asyncio

from src.mqtt_discovery_service import MQTTDiscoveryService
from src.grpc_stream_reader import GRPCDeviceFramesReader
from src.formatting import FrameLogItemToRecordsFormatter
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

    async def _run():
        async with InfluxDBWriter() as writer:
            with FrameLogItemToRecordsFormatter(writer.write) as formatter:
                async with GRPCDeviceFramesReader(formatter.format) as reader:
                    with MQTTDiscoveryService(reader.read) as service:
                        await service.start()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Service interrupted. Shutting down...")


if __name__ == "__main__":
    sys.exit(main())
