import json

from .logger import logger


def _flatten_nested_dict(y: dict) -> dict:
    out = {}

    def do_flatten(x, name=""):
        if type(x) is dict:
            for k in x:
                do_flatten(x[k], name + k + ".")
        else:
            out[name[:-1]] = x

    do_flatten(y)
    return out


def _new_point_dict(time: str, measurement: str, tags: dict):
    return {
        "time": time,
        "measurement": measurement,
        "tags": tags,
        "fields": {},
        "field_types": {},
    }


def frame_log_item_to_records(data: dict) -> list[dict]:
    data["body"] = json.loads(data["body"])  # deserialize body
    return _deserialized_frame_log_item_to_records(data)


def _deserialized_frame_log_item_to_records(data: dict) -> list[dict]:
    is_uplink = _validate_frame_log_item_format(data)

    if is_uplink:
        records = _uplink_frame_log_item_to_records(data)
    else:  # is_downlink
        records = _downlink_frame_log_item_to_records(data)

    return records


def _validate_frame_log_item_format(data):
    body, properties = data["body"], data["properties"]
    # downlinks do not have the rx_info field in the body
    # and they have an additional "Gateway ID" property
    if "rx_info" in body and not "Gateway ID" in properties:
        return True
    elif "Gateway ID" in properties and not "rx_info" in body:
        return False
    else:
        raise ValueError(f"Unknown frame LogItem format: {data}")


def _uplink_frame_log_item_to_records(data: dict) -> list[dict]:
    FIELDS = ("rssi", "snr")

    time = data.pop("time")  # influxdb does not like the "time" tag
    rx_info = data["body"].pop("rx_info")
    data = _apply_common_frame_log_item_formatting(data)
    tags = _flatten_nested_dict(data)

    records = []
    for rx in [_flatten_nested_dict(rx) for rx in rx_info]:
        p = _new_point_dict(time, "device_uplink_frame_log", tags)
        for f in (f for f in FIELDS if f in rx):
            p["fields"][f] = rx.pop(f)
            p["field_types"][f] = "float"
        p["tags"].update(rx)
        records.append(p)

    return records


def _downlink_frame_log_item_to_records(data: dict) -> list[dict]:
    time = data.pop("time")  # influxdb does not like the "time" tag
    data["gateway_id"] = data["properties"].pop("Gateway ID")
    data = _apply_common_frame_log_item_formatting(data)
    tags = _flatten_nested_dict(data)

    records = []
    p = _new_point_dict(time, "device_downlink_frame_log", tags)
    p["fields"]["value"] = 1  # no useful field
    records.append(p)

    return records


def _apply_common_frame_log_item_formatting(data: dict) -> dict:
    body = data.pop("body")  # consume body, flatten fields
    data["phy_payload"] = json.dumps(body.pop("phy_payload"))  # keep serialized
    data["tx_info"] = body.pop("tx_info")

    properties = data.pop("properties")  # consume properties, flatten fields
    data["dev_eui"] = properties.pop("DevEUI")
    data["dev_addr"] = properties.pop("DevAddr")

    return data


class FrameLogItemToRecordsFormatter:
    def __init__(self, on_format):
        self._on_format = on_format

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    async def format(self, data: dict):
        try:
            records = frame_log_item_to_records(data)
            await self._on_format(records)
        except Exception as e:
            logger.error(f"Formatting error: {e}")
