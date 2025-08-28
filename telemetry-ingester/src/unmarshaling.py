from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message
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

UnknownEventType = KeyError


def unmarshal_mqtt_event_to_dict(payload: bytes, event_type: str) -> dict:
    try:
        protobuf_message = CHIRPSTACK_EVENTS[event_type]()
    except KeyError as e:
        raise UnknownEventType(f"Unknown ChirpStack event type: {e}")
    protobuf_message.ParseFromString(payload)
    return unmarshal_protobuf_message_to_dict(protobuf_message)


def unmarshal_protobuf_message_to_dict(message: Message) -> dict:
    return MessageToDict(
        message,
        always_print_fields_with_no_presence=True,
        preserving_proto_field_name=True,
    )
