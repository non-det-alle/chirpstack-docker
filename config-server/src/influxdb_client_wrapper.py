from influxdb_client import InfluxDBClient, QueryApi
import pandas as pd


class InfluxDBClientWrapper:
    def __init__(self, url: str, token: str, org: str, bucket: str) -> None:
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket

    def __enter__(self):
        self.client = InfluxDBClient(self.url, token=self.token, org=self.org)
        self.query_api: QueryApi = self.client.query_api()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.client.close()

    def get_uplink_records(
        self, dev_eui: str, start: str, stop: str = "now()"
    ) -> pd.DataFrame:
        """Get DataFrame cointaining database records on uplink frames for a device.

        Args:
            dev_eui: EUI identifier of a device we want to query data of.
            start: Start time of the time windows of data to be retrieved. Can be relative duration, absolute time, or integer (Unix timestamp in seconds). For example, "-1h", "2019-08-28T22:00:00Z", or "1567029600".
            stop (optional): See start for possible values. Defaults to "now()".
        """
        query = f'from(bucket: "{self.bucket}") \
            |> range(start: {start}, stop: {stop}) \
            |> filter(fn: (r) => r._measurement == "device_uplink") \
            |> filter(fn: (r) => r.dev_eui == "{dev_eui}") \
            |> filter(fn: (r) => r._field != "value") \
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'
        df = self.query_api.query_data_frame(query, org=self.org)
        if not isinstance(df, pd.DataFrame):
            raise ValueError("Queried object is not a DataFrame")
        if df.empty:
            raise ValueError("Not enough records in the database.")
        return (
            df.drop(columns=["result", "table"])
            .set_index("_time")
            .drop_duplicates()
            .sort_index()
        )
