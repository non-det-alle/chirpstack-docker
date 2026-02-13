import signal
import sys
import time
import os
from pprint import pprint as pp

from chirpstack_api.api import DeviceConfigStore
import toml

# ChirpStack API imports
from chirpstack_client import ChirpStackClient, to_dict

# InfluxDB API imports
from influxdb_client_wrapper import InfluxDBClientWrapper

#            CONTROL LOOP: ARCHITECTURE AND INFORMATION FLOW DIAGRAM
#
#                     _________________                  _________________
#                    |                 |  [2] past      |                 |
#                    |  Config Server  |      metrics   | Metrics Storage |
#                    |     (this)      | <------------- |    (influxdb)   |
#                    |_________________|                |_________________|
#                        ^ /                                ^
#                       / /                                /
#        [3] device    / / [4] new device                 / [1.b] uplink &
#            state &  / /      configs                   /        downlink
#            configs / /                                /         frame logs
#                   / /                                /
#                  / v                                /
#       ________________                      ____________________
#      |                |                    |                    |
#      |                | -----------------> | Telemetry Ingester |
#      |                |  [1.a] uplink &    |       (this)       |
#      | LoRaWAN Server |        downlink    |____________________|
#      |  (chirpstack)  |        frame logs
#      |                |
#      |                |
#      |________________|
#           / / | \ \
#          /         \
#         /           \
#        /             \
#      GW_1   . . .   GW_n   Gateways
#
#     ~~~ Radio channel ~~~
#
#       ED_1  . . .  ED_m    End Devices
#
#
# Communication protocols:
# - RESP [1.a]
# - REST [1.b], [2]
# - gRPC [3], [4]
#
# Detailed overview:
# [1] uplink & downlink frame logs: packet metadata streamed from ChirpStack's
#     logging backend (via REdis Serialization Protocol (RESP) [1.a]) and
#     forwarded to the Metrics Storage function (via InfluxDB REST API [1.b]) by
#     the Telemetry Ingester.
# [2] past metrics: past records and metrics being queried by the Config Server
#     (using the InfluxDB REST API and the Flux query language). Metrics
#     aggregation can happen either in the Storage using Flux queries, or
#     directly in the Config Server (less optimal in distributed settings).
# [4] device state & configs: known parameter state of the device and current
#     configuration stored in the server, obtained using ChirpStack's gRPC API.
#     Together with traffic metrics, this information should be used in the
#     decision making process to evaluate if a desired configuration is
#     compatible with or needed for the device.
# [4] new device config: new configuration for the device sent by the Config
#     Server to ChirpStack's device configuration storage (via gRPC API).


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "-c":
        print("Usage: python start.py -c <path/to/config/file/dir>")
        return 1
    c = toml.load(sys.argv[2] + "/config-server.toml")

    # Unpack network configs
    c["influxdb"]["url"] = "http://" + c["influxdb"]["endpoint"]
    with open(os.environ["CHIRPSTACK_API_TOKEN_FILE"], "r") as f:
        c["chirpstack"]["api_token"] = f.readline().rstrip("\n")

    # Number of seconds between reconfiguration triggers
    period = 5

    # Time frame for aggregation of metrics
    history = "30m"

    # Desired uplink channels if PDR >70%
    reduced_chmask = [0, 5, 7]

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

        def healthcheck(dev_eui: str):
            ##############################################
            # Making use of the data collection pipeline #
            ##############################################

            uplink_records = db_client.get_records(f"-{history}", dev_eui=dev_eui)

            if uplink_records.empty:
                print("Not enough records in the database. Postponed.")
                return

            fcnt_col = "phy_payload.payload.fhdr.f_cnt"
            # Remove null-values, if any
            uplink_records = uplink_records.dropna(subset=fcnt_col)
            # Deduplicate multi-RX rows
            uplink_records = uplink_records.groupby(["_time", "log_id"]).first()
            # Sort by timestamp
            uplink_records = uplink_records.sort_values("_time")
            # Time-sorted list of frame counters
            f_cnts = uplink_records[fcnt_col].astype(int)

            # Compute Packet Delivery Ratio (PDR)
            recv = f_cnts.count()
            sent = f_cnts.diff()
            # Manage f_cnt resets
            sent = sent.mask(sent < 0, None).fillna(1).sum()
            pdr = recv / sent
            print(f"{dev_eui} PDR of past {history}: {pdr} ({recv}/{int(sent)})")

            ####################################################
            # Giving ChirpStack configs for the LoRaWAN device #
            ####################################################

            # Some random values for show. Each field is optional.
            dr, tx_power_index, nb_trans, max_duty_cycle = (0, 2, 3, 7)
            # (Example: Restrict the number of channels if PDR is >70%)
            chmask = reduced_chmask if pdr >= 0.7 else list(range(8))
            print(f"{dev_eui} ChMask config: {chmask}")

            # Check if configuration is already good to go
            if dev_eui in cs_client.list_configured_devices(application_id):
                config_store = cs_client.get_device_config(dev_eui)
                print(f"{dev_eui} GET DeviceConfigStore: {to_dict(config_store)}")
                if chmask == config_store.enabled_uplink_channel_indices:
                    # Log current device configuration aligment
                    align = cs_client.get_device_config_alignment(dev_eui)
                    print(f"{dev_eui} GET DeviceConfigAlignment: {to_dict(align)}")
                    return

            try:
                # Check if configuration is compatible with installed channels
                current_params = cs_client.get_device_current_params(dev_eui)
                print(f"{dev_eui} GET DeviceCurrentParams: ", end=None)
                pp(to_dict(current_params), width=120)
                if any(ch not in current_params.channels.keys() for ch in chmask):
                    print(f"{dev_eui} Configuration not compatible (chmask: {chmask})")
                    return
            except ValueError as e:
                print(f"{e}. Postponed.")
                return

            # Set chmask and other configs
            config_store = DeviceConfigStore(
                enabled_uplink_channel_indices=chmask,
                dr=dr,
                tx_power_index=tx_power_index,
                nb_trans=nb_trans,
                max_duty_cycle=max_duty_cycle,
            )
            print(f"{dev_eui} SET DeviceConfigStore({to_dict(config_store)})")
            cs_client.set_device_config(dev_eui, config_store)

        @on_sigterm
        def cleanup():
            print("Cleaning up stored configurations")
            for dev_eui in cs_client.list_configured_devices(application_id):
                cs_client.delete_device_config(dev_eui)
                print(f"{dev_eui} DELETE DeviceConfigStore")

        try:
            while True:
                # check if devices need reconfiguration
                devices = cs_client.get_dev_euis(application_id)
                print(f"\nDevice EUIs: {devices}")
                [healthcheck(dev_eui) for dev_eui in devices]
                time.sleep(period)
        except KeyboardInterrupt as e:
            print(e)
            cleanup()


def on_sigterm(f):
    def handler(*_):
        f()
        # restore and propagate
        signal.signal(signal.SIGTERM, default)
        signal.raise_signal(signal.SIGTERM)

    default = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, handler)
    return f


if __name__ == "__main__":
    sys.exit(main())
