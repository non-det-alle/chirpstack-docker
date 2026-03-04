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

    def get_traffic_records(
        self,
        start: str,
        stop: str = "now()",
        dev_eui: str | list[str] | None = None,
        direction: str = "u",
        exclude_join: bool = True,
    ) -> pd.DataFrame:
        """Get DataFrame containing frame_log records of frames.

        Args:
            start: Start time of the time windows of data to be retrieved. Can be
                relative duration, absolute time, or integer (Unix timestamp in seconds).
                For example, "-1h", "2019-08-28T22:00:00Z", or "1567029600".
            stop (optional): See start for possible values. Defaults to "now()".
            dev_eui: EUI identifier for a device (or list of) to query data for.
            direction: Whether to pull uplink ('u'), downlink ('d') or both ('b') traffic
                records.
        """

        query = f'from(bucket: "{self.bucket}") |> range(start: {start}, stop: {stop})'

        if dev_eui:
            if type(dev_eui) == str:
                dev_eui = [dev_eui]
            fmt = "[" + ",".join([f'"{v}"' for v in dev_eui]) + "]"
            query += f" |> filter(fn: (r) => contains(value: r.dev_eui, set: {fmt}))"

        if exclude_join and (direction == "u" or direction == "b"):
            f_type = "JoinRequest"
            query += f'|> filter(fn: (r) => r["phy_payload.mhdr.f_type"] != "{f_type}")'
        if exclude_join and (direction == "d" or direction == "b"):
            f_type = "JoinAccept"
            query += f'|> filter(fn: (r) => r["phy_payload.mhdr.f_type"] != "{f_type}")'

        if direction == "u":
            query += (
                ' |> filter(fn: (r) => r._measurement == "device_uplink_frame_log")'
                ' |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'
                " |> group()"
            )
        elif direction == "d":
            query += (
                ' |> filter(fn: (r) => r._measurement == "device_downlink_frame_log")'
                ' |> drop(columns: ["_field", "_value"])'
                " |> group()"
            )

        return pd.DataFrame(self.query_api.query_data_frame(query, org=self.org))
