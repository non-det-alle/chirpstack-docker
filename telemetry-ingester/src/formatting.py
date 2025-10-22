import enum
import json

from .logger import getLogger
from .config import settings


def _flatten_nested_dict(y: dict) -> dict:
    out = {}

    def _do_flatten(x, name=""):
        if type(x) is dict:
            for k in x:
                _do_flatten(x[k], name + k + ".")
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


def _flatten_frame_log_item(log_item: dict) -> dict:
    out = {}

    out["log_item_id"] = log_item["id"]
    out["time"] = log_item["time"]
    # log_item["description"]: ignored, f_type already in phy_payload

    body = json.loads(log_item["body"])  # deserialize body
    out["phy_payload"] = body["phy_payload"]
    out["tx_info"] = body["tx_info"]
    if "rx_info" in body:  # uplink
        out["rx_info"] = body["rx_info"]

    properties = log_item["properties"]
    out["dev_eui"] = properties["DevEUI"]
    out["dev_addr"] = properties["DevAddr"]
    if "Gateway ID" in properties:  # downlink
        out["gateway_id"] = properties["Gateway ID"]

    return out


def _is_uplink_frame_data(data):
    # downlinks do not have the rx_info field in the body
    # and they have an additional "Gateway ID" property
    if "rx_info" in data and not "gateway_id" in data:
        return True
    elif "gateway_id" in data and not "rx_info" in data:
        return False
    else:
        raise ValueError(f"Unknown frame LogItem format: {data}")


def _uplink_frame_data_to_records(data: dict) -> list[dict]:
    FIELDS = ("rssi", "snr")

    time = data.pop("time")  # influxdb does not like the "time" tag
    rx_info = data.pop("rx_info")
    tags = _flatten_nested_dict(data)

    records = []
    for rx in [_flatten_nested_dict(rx) for rx in rx_info]:
        p = _new_point_dict(time, "device_uplink_frame_log", tags)
        for f in (f for f in FIELDS if f in rx):
            p["fields"][f] = rx.pop(f)
            p["field_types"][f] = "float"
        p["tags"].update({"rx_info." + k: v for k, v in rx.items()})
        records.append(p)

    return records


def _downlink_frame_data_to_records(data: dict) -> list[dict]:
    time = data.pop("time")  # influxdb does not like the "time" tag
    tags = _flatten_nested_dict(data)

    records = []
    p = _new_point_dict(time, "device_downlink_frame_log", tags)
    p["fields"]["value"] = 1  # no useful field
    records.append(p)

    return records


def frame_log_item_to_records(log_item: dict) -> list[dict]:
    data = _flatten_frame_log_item(log_item)
    if _is_uplink_frame_data(data):
        return _uplink_frame_data_to_records(data)
    else:  # is_downlink
        return _downlink_frame_data_to_records(data)


class FrameLogItemToRecordsFormatter:
    def __init__(self, on_format, log_level: None | str = None):
        self.log = getLogger(self.__class__.__name__)
        self.log.setLevel(log_level if log_level else settings.LOG_LEVEL)

        self._on_format = on_format

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    async def format(self, log_item: dict):
        try:
            records = frame_log_item_to_records(log_item)
            await self._on_format(records)
        except Exception as e:
            self.log.error(f"Formatting error: {e}")
