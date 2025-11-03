from .logger import getLogger
from .config import settings


def _flatten_nested_dict(y: dict) -> dict:
    out = {}

    def _do_flatten(x, name=""):
        if type(x) is dict:
            for key, val in x.items():
                _do_flatten(val, name + key + ".")
        else:
            out[name[:-1]] = x

    _do_flatten(y)
    return out


def _new_point_dict(time: str, measurement: str, tags: dict):
    return {
        "time": time,
        "measurement": measurement,
        "tags": tags,
        "fields": {},
        "field_types": {},
    }


class LogsFormatter:
    def __init__(self, on_format, log_level: None | str = None):
        self._log = getLogger(self.__class__.__name__)
        self._log.setLevel(log_level if log_level else settings.LOG_LEVEL)

        self.UPLINK_FIELDS = (
            ("rx_info.rssi", "float"),
            ("rx_info.snr", "float"),
        )

        self._on_format = on_format

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def _to_records(self, frame_log: dict):
        copy = frame_log  # idempotency
        # time, log_id, dev_eui, phy_payload, tx_info, [rx_info]
        time = copy.pop("time")  # influxdb does not like the "time" tag
        rx_info = copy.pop("rx_info")
        tags = _flatten_nested_dict(copy)
        if rx_info:  # uplink
            for rx in rx_info:
                rx = {"rx_info." + k: v for k, v in _flatten_nested_dict(rx).items()}
                p = _new_point_dict(time, "device_uplink_frame_log", tags | rx)
                for field, type in self.UPLINK_FIELDS:
                    if field not in p["tags"]:
                        self._log.warning(f"{field} field not found in uplink data")
                    p["fields"][field] = p["tags"].pop(field, None)
                    p["field_types"][field] = type
                yield p
        else:  # downlink
            p = _new_point_dict(time, "device_downlink_frame_log", tags)
            p["fields"]["value"] = 1  # no useful field
            yield p

    def format(self, frame_logs: list[dict]):
        try:
            records = [p for log in frame_logs for p in self._to_records(log)]
            self._log.debug(f"Formatted records: {records}")
            self._on_format(records)
        except Exception as e:
            self._log.error(f"Formatting error: {e}")
