from google.protobuf.json_format import MessageToDict
from chirpstack_api import integration

CHIRPSTACK_EVENTS = {
    "up": integration.UplinkEvent,
    "status": integration.StatusEvent,
    "join": integration.JoinEvent,
    "ack": integration.AckEvent,
    "txack": integration.TxAckEvent,
    "log": integration.LogEvent,
    "location": integration.LocationEvent,
    "integration": integration.IntegrationEvent,
}


def unmarshal_mqtt_event_to_dict(payload: bytes, event: str) -> dict:
    protobuf_message = CHIRPSTACK_EVENTS[event]()
    protobuf_message.ParseFromString(payload)
    return MessageToDict(
        protobuf_message,
        always_print_fields_with_no_presence=True,
        preserving_proto_field_name=True,
    )
