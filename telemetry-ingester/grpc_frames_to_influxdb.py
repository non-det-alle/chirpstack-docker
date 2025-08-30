import os
import sys
import asyncio

from src.grpc_discovery_service import GRPCGatewayDiscoveryService
from src.grpc_stream_reader import GRPCGatewayFramesReader
from src.formatting import FrameLogItemToRecordsFormatter
from src.influxdb_writer import InfluxDBWriterAsync
from src.config import settings
from src.logger import logger


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "-c":
        file = os.path.basename(__file__)
        print(f"Usage: python {file} -c <path/to/config/dir>")
        return 1

    settings.load(sys.argv[2])
    logger.setLevel(settings.LOG_LEVEL)

    async def run():
        async with InfluxDBWriterAsync() as writer:
            with FrameLogItemToRecordsFormatter(writer.write) as formatter:
                async with GRPCGatewayFramesReader(formatter.format) as reader:
                    async with GRPCGatewayDiscoveryService(reader.read) as service:
                        await service.start(poll_interval=5)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Service interrupted. Shutting down...")


if __name__ == "__main__":
    sys.exit(main())
