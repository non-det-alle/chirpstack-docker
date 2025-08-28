from influxdb_client.client.influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.write.point import Point

from .logger import logger
from .config import settings


class InfluxDBWriter:
    def __init__(self):
        self._url = settings.INFLUXDB_URL
        self._token = settings.INFLUXDB_TOKEN
        self._org = settings.INFLUXDB_ORG
        self._bucket = settings.INFLUXDB_BUCKET

        self._client = InfluxDBClient(self._url, self._token, org=self._org)
        self._write_api = self._client.write_api(SYNCHRONOUS)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self):
        self._client.close()

    def write(self, records: list[dict]):
        try:
            points = [Point.from_dict(p) for p in records]
            self._write_api.write(self._bucket, record=points)
            logger.debug(f"Written to InfluxDB: {records}")
        except Exception as e:
            logger.exception(f"Failed to write to InfluxDB: {e}")
