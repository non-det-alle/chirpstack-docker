import sys
import time

from src.utilities import NetworkServer, DataBase

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

import src.freq_streering as algorithm

# import global algorithm configs to edit them
from src.freq_streering import LOOKBACK_ORIZON

CONTROL_LOOP_PERIODICITY = 60 # seconds

def main():
    with NetworkServer() as ns, DataBase() as db:
        try:
            while True:
                algorithm.run(ns, db)
                time.sleep(CONTROL_LOOP_PERIODICITY)
        except KeyboardInterrupt as e:
            algorithm.cleanup(ns)
            print("Cleared configs")


if __name__ == "__main__":
    sys.exit(main())
