import json
import re

from .logger import getLogger
from .config import settings

# [A-Z][a-z]+ any uppercase letter followed by 1+ lowercase
# (?!^) not at the start of the string ^
# (?<!_) not preceded by _
# or |
# [A-Z] any uppercase letter
# (?<=[a-z0-9]) preceded by one lowercase letter or number
_c2s = re.compile("((?!^)(?<!_)[A-Z][a-z]+|(?<=[a-z0-9])[A-Z])")


def _camel_to_snake(s: str) -> str:
    return _c2s.sub(r"_\1", s).lower()


def _flatten_nested_dict(y: dict) -> dict:
    out = {}

    def _do_flatten(x, name=""):
        if type(x) is dict:
            for key, val in x.items():
                key = _camel_to_snake(key)
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


class FrameLogItemToRecordsFormatter:
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

    def _parse_log_item(self, log_item: dict) -> dict:
        # LogItem: id, time, description, body, properties
        out = {}

        out["time"] = log_item["time"]
        out["log_item_id"] = log_item["id"]
        # log_item["description"]: f_type already in phy_payload

        properties = log_item["properties"]
        out["dev_eui"] = properties["DevEUI"]
        # properties["DevAddr"]: devaddr already in phy_payload
        if "Gateway ID" in properties:  # downlink
            out["gateway_id"] = properties["Gateway ID"]

        body = json.loads(log_item["body"])  # deserialize body
        out["phy_payload"] = body["phy_payload"]
        out["tx_info"] = body["tx_info"]
        if "rx_info" in body:  # uplink
            out["rx_info"] = body["rx_info"]

        return out

    def _is_uplink(self, data):
        # downlinks do not have the rx_info field in the body
        # and they have an additional "gateway_id" property
        if "rx_info" in data and not "gateway_id" in data:
            return True
        elif "gateway_id" in data and not "rx_info" in data:
            return False
        else:
            raise ValueError(f"Unknown frame LogItem format: {data}")

    def _uplink_to_records(self, data: dict) -> list[dict]:
        copy = data  # idempotency

        time = copy.pop("time")  # influxdb does not like the "time" tag
        rx_info = copy.pop("rx_info")
        tags = _flatten_nested_dict(copy)

        records = []
        for rx in rx_info:
            rx = {"rx_info." + k: v for k, v in _flatten_nested_dict(rx).items()}
            p = _new_point_dict(time, "device_uplink_frame_log", tags | rx)
            for field, type in self.UPLINK_FIELDS:
                if field not in p["tags"]:
                    self._log.warning(f"{field} field not found in uplink data")
                p["fields"][field] = p["tags"].pop(field, None)
                p["field_types"][field] = type
            records.append(p)

        return records

    def _downlink_to_records(self, data: dict) -> list[dict]:
        copy = data  # idempotency

        time = copy.pop("time")  # influxdb does not like the "time" tag
        tags = _flatten_nested_dict(copy)

        records = []
        p = _new_point_dict(time, "device_downlink_frame_log", tags)
        p["fields"]["value"] = 1  # no useful field
        records.append(p)

        return records

    async def format(self, log_item: dict):
        try:
            data = self._parse_log_item(log_item)
            if self._is_uplink(data):
                records = self._uplink_to_records(data)
            else:  # is_downlink
                records = self._downlink_to_records(data)
            await self._on_format(records)
        except Exception as e:
            self._log.error(f"Formatting error: {e}")
