from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client.client.influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.write.point import Point

from .logger import getLogger
from .config import settings


class InfluxDBWriter:
    def __init__(self, log_level: None | str = None):
        self._url = settings.INFLUXDB_URL
        self._token = settings.INFLUXDB_TOKEN
        self._org = settings.INFLUXDB_ORG
        self._bucket = settings.INFLUXDB_BUCKET

        self._log = getLogger(self.__class__.__name__)
        self._log.setLevel(log_level if log_level else settings.LOG_LEVEL)

        self._client = InfluxDBClientAsync(self._url, self._token, self._org)
        self._write_api = self._client.write_api()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()

    async def close(self):
        await self._client.close()

    async def write(self, records: list[dict]):
        try:
            points = [Point.from_dict(p) for p in records]
            assert await self._write_api.write(self._bucket, record=points)
            self._log.debug(f"Written to InfluxDB: {records}")
        except Exception as e:
            self._log.error(f"Failed to write to InfluxDB: {e}")
