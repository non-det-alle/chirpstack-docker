EVENT_HANDLERS = {}

MissingHandler = KeyError


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


# TODO: implement missing handlers
def event_to_records(data: dict, event_type: str) -> list[dict]:
    if event_type not in EVENT_HANDLERS:
        raise MissingHandler(f'Format handler not implemented for event "{event_type}"')
    return EVENT_HANDLERS[event_type](data)


def event_handler(event: str):
    def register_handler(f):
        EVENT_HANDLERS[event] = f
        return f

    return register_handler


@event_handler("up")
def on_uplink_event(up: dict) -> list[dict]:
    FIELDS = ("rssi", "snr")

    time = up.pop("time")  # influxdb does not like the "time" tag
    rx_info = [_flatten_nested_dict(rx) for rx in up.pop("rx_info")]
    tags = _flatten_nested_dict(up)

    points = []
    for rx in rx_info:
        p = _new_point_dict(time, "device_uplink_rx_info", tags)
        for f in (f for f in FIELDS if f in rx):
            p["fields"][f] = rx.pop(f)
            p["field_types"][f] = "float"
        p["tags"].update(rx)
        points.append(p)

    return points
