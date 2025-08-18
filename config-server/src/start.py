# ChirpStack API imports
from chirpstack_client import ChirpStackClient

# InfluxDB API imports
from influxdb_client_wrapper import InfluxDBClientWrapper

# MQTT subcriber imports
import paho.mqtt.subscribe as mqtt_subscribe
import paho.mqtt.client as mqtt
from google.protobuf.json_format import Parse
from chirpstack_api.integration import UplinkEvent

import pandas as pd
import toml
import sys
import time
import os

#        CONTROL LOOP: ARCHITECTURE AND INFORMATION FLOW DIAGRAM
#
#                       _________________                  _________________
#                      |                 |  [3] past      |                 |
#                      |  Config Server  |      metrics   | Metrics Storage |
#                      |     (this)      | <------------- |    (influxdb)   |
#                      |_________________|                |_________________|
#                        ^           ^ \                    ^
#                       /             \ \                  /
#       [2.a] uplink   /    [4] device \ \ [5] new        / [2.b] uplink
#             metrics /         state & \ \    configs   /        metrics
#                    /          configs  \ \            /
#                   /                     \ \          /
#                  /                       \ ⌄        /
#       _____________                    ________________
#      |             |   [1] uplink     |                |
#      |             | ---------------> |                |
#      |             | <--------------- |                |
#      | MQTT Broker |   [2.a] uplink   | LoRaWAN Server |
#      | (mosquitto) |         metrics  |  (chirpstack)  |
#      |             |                  |                |
#      |             | <--------------- |                |
#      |_____________|   [6] downlink   |________________|
#         / / | \ \
#        /         \
#       /           \
#      /             \
#    GW_1   . . .   GW_n   Gateways
#
#   ~~~ Radio channel ~~~
#
#     ED_1  . . .  ED_m    End Devices
#
#
# Communication protocols:
# - MQTT [1], [2.a], [6]
# - REST [2.b], [3]
# - gRPC [4], [5]
#
# Detailed overview:
# [1] uplink: uplink message received from a gateway being relayed to
#     ChirpStack by the MQTT broker.
# [2] uplink metrics: message metadata being distpatched by ChirpStack to the
#     Config Server (via MQTT topic subscription [2.a]) and to the Metrics
#     Storage (via InfluxDB REST API [2.b]).
# [3] past metrics: past uplink records and metrics being queried by the Config
#     Server (using the InfluxDB REST API and the Flux query language).
#     Metrics aggregation can happen either in the Storage using Flux queries,
#     or directly in the Config Server (less optimal in distributed settings).
# [4] device state & configs: known parameter state of the device and current
#     configuration stored in the server, obtained using ChirpStack's gRPC API.
#     Together with traffic metrics, this information should be used in the
#     decision making process to evaluate if a needed configuration is
#     compatible or needed by the device.
# [5] new config: new configuration for the device sent by the Config Server to
#     ChirpStack's device configuration storage (via gRPC API). This should be
#     skipped if no configuration is needed.
# [6] downlink: downlink message from ChirpStack to a device. This message is
#     relayed by the MQTT broker to the correct gateway, that will send it over
#     the Radio channel at the right time to meet the reception window of the
#     device. New configurations are inserted in the downlink packet:
#     ChirpStack has a dedicated parameter to increase the amount of time it
#     will wait before creating the downlink, allowing for configurations to be
#     added.


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "-c":
        print("Usage: python start.py -c <path/to/config/file/dir>")
        return 1
    c = toml.load(sys.argv[2] + "/config-server.toml")

    # Unpack network configs
    c["influxdb"]["url"] = "http://" + c["influxdb"]["endpoint"]
    c["mosquitto"]["hostname"] = c["mosquitto"]["endpoint"].split(":")[0]
    c["mosquitto"]["port"] = c["mosquitto"]["endpoint"].split(":")[1]
    with open(os.environ["CHIRPSTACK_API_TOKEN_FILE"], "r") as f:
        c["chirpstack"]["api_token"] = f.readline().rstrip("\n")

    # Time frame for aggregation of metrics
    history = "30m"

    # Desired uplink channels if PDR >70%
    reduced_chmask = [0, 5, 7]

    # Threshold for disconnect and cleanup (-1 is never)
    max_messages = -1

    # Simple synchronous subscriber producing configurations on uplink message events
    with ChirpStackClient(
        c["chirpstack"]["endpoint"],
        c["chirpstack"]["api_token"],
    ) as cs_client, InfluxDBClientWrapper(
        c["influxdb"]["url"],
        c["influxdb"]["token"],
        c["influxdb"]["org"],
        c["influxdb"]["bucket"],
    ) as db_client:
        while True:
            try:
                tenant_id = cs_client.get_tenant_id(c["chirpstack"]["tenant_name"])
                application_ids = cs_client.get_application_ids(tenant_id)
                if not application_ids:
                    raise ValueError("Missing application.")
                application_id = application_ids[0]
            except ValueError as e:
                print(f"{e} Retrying in 1s.\n")
                time.sleep(1)
                continue
            break
        cs_client.get_dev_euis(application_id)  # this is here just to showcase the API

        # this is what's called when an uplink is detected
        def on_uplink(mqtt_client: mqtt.Client, userdata, message: mqtt.MQTTMessage):
            print(f"\n\n{message.topic}")
            uplink_event = Parse(message.payload, UplinkEvent())
            dev_eui = uplink_event.device_info.dev_eui

            ##############################################
            # Making use of the data collection pipeline #
            ##############################################
            try:
                uplink_records = db_client.get_uplink_records(dev_eui, f"-{history}")
            except ValueError as e:
                print(f"{e} Postponed.")
                return
            # Time series of frame counters
            f_cnts = uplink_records["f_cnt"].astype(int)
            # Add latest record if missing
            if f_cnts.iat[-1] != uplink_event.f_cnt:
                # avoid gw reception time (uplink_event.time), it can mess up order
                f_cnts[pd.Timestamp.now("UTC")] = uplink_event.f_cnt
                f_cnts = f_cnts.sort_index()
            # Compute Packet Delivery Ratio (PDR)
            recv = f_cnts.count()
            sent = f_cnts.diff()
            # Manage f_cnt resets
            sent = sent.mask(sent < 0, None).fillna(1).sum()
            pdr = recv / sent
            print(f"PDR of past {history}: {pdr} ({recv}/{int(sent)})")

            ####################################################
            # Giving ChirpStack configs for the LoRaWAN device #
            ####################################################
            # (Example: Restrict the number of channels if PDR is >70%)
            chmask = reduced_chmask if pdr >= 0.7 else list(range(8))
            # Log current device configuration aligment
            _ = cs_client.get_device_config_alignment(dev_eui)
            # Check compatibility with installed channels
            if not cs_client.is_chmask_compatible(chmask, dev_eui):
                print(f"Configuration not compatible (chmask: {chmask})")
                return
            # Set chmask
            time.sleep(2)  # comment out for immediate chmask configuration
            cs_client.set_chmask_for_device(chmask, dev_eui)

            # Cleanup and disconnect after N messages
            userdata["message_count"] += 1
            if max_messages != -1 and userdata["message_count"] >= max_messages:
                for dev_eui in cs_client.list_configured_devices(application_id):
                    cs_client.delete_device_config(dev_eui)
                mqtt_client.disconnect()

        mqtt_subscribe.callback(
            on_uplink,
            f"application/{application_id}/device/+/event/up",
            hostname=c["mosquitto"]["hostname"],
            port=int(c["mosquitto"]["port"]),
            userdata={"message_count": 0},
        )


if __name__ == "__main__":
    sys.exit(main())
