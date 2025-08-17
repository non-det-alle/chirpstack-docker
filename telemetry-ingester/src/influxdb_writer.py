from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from src.logger import logger
from src.config import settings


class InfluxDBWriter:
    def __init__(self):
        self.client = InfluxDBClient(
            url=settings.INFLUXDB_URL,
            token=settings.INFLUXDB_TOKEN,
            org=settings.INFLUXDB_ORG,
        )
        self.bucket = settings.INFLUXDB_BUCKET
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def write(self, records: list[dict]):
        try:
            points = [Point.from_dict(p) for p in records]
            self.write_api.write(bucket=self.bucket, record=points)
            logger.debug(f"Written to InfluxDB: {records}")
        except Exception as e:
            logger.exception(f"Failed to write to InfluxDB: {e}")
