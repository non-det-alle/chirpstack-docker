# ChirpStack API imports
import grpc
from chirpstack_api import api

# InfluxDB2 API imports
from influxdb_client import InfluxDBClient, QueryApi

# MQTT subcriber imports
import paho.mqtt.subscribe as mqtt_subscribe
import paho.mqtt.client as mqtt
from google.protobuf.json_format import Parse
from chirpstack_api.integration import UplinkEvent

import pandas as pd
import toml
import sys
import time


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "-c":
        print("Usage: python start.py -c <path/to/network/c/file>")
        return 1
    c = toml.load(sys.argv[2])

    # Unpack network configs
    c["influxdb2"]["url"] = "http://" + c["influxdb2"]["endpoint"]
    c["mosquitto"]["hostname"] = c["mosquitto"]["endpoint"].split(":")[0]
    c["mosquitto"]["port"] = c["mosquitto"]["endpoint"].split(":")[1]

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
        c["influxdb2"]["url"],
        c["influxdb2"]["token"],
        c["influxdb2"]["org"],
        c["influxdb2"]["bucket"],
    ) as db_client:
        while True:
            try:
                tenant_id = cs_client.get_tenant_id(c["chirpstack"]["tenant_name"])
                application_id = cs_client.get_application_ids(tenant_id)[0]
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
            # Set chmask if compatible
            cs_client.get_device_config_alignment(dev_eui)
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


class InfluxDBClientWrapper:
    def __init__(self, url, token, org, bucket):
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket

    def __enter__(self):
        self.client = InfluxDBClient(self.url, token=self.token, org=self.org)
        self.query_api: QueryApi = self.client.query_api()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.client.close()

    def get_uplink_records(self, dev_eui, start, stop="now()") -> pd.DataFrame:
        """Get DataFrame cointaining database records on uplink frames for a device.

        Args:
            dev_eui (str): EUI identifier of a device we want to query data of.
            start (str): Start time of the time windows of data to be retrieved. Can be relative duration, absolute time, or integer (Unix timestamp in seconds). For example, "-1h", "2019-08-28T22:00:00Z", or "1567029600".
            stop (str, optional): See start for possible values. Defaults to "now()".
        """
        query = f'from(bucket: "{self.bucket}") \
            |> range(start: {start}, stop: {stop}) \
            |> filter(fn: (r) => r._measurement == "device_uplink") \
            |> filter(fn: (r) => r.dev_eui == "{dev_eui}") \
            |> filter(fn: (r) => r._field != "value") \
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'
        df = self.query_api.query_data_frame(query, org=self.org)
        if df.empty:
            raise ValueError("Not enough records in the database.")
        return (
            df.drop(columns=["result", "table"])
            .set_index("_time")
            .sort_index()
            .drop_duplicates()
        )


class ChirpStackClient:
    def __init__(self, endpoint, token):
        self.endpoint = endpoint
        self.metadata = [("authorization", "Bearer %s" % token)]

    def __enter__(self):
        self.channel = grpc.insecure_channel(self.endpoint)
        self.config_store_api = api.DeviceConfigStoreServiceStub(self.channel)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.channel.close()

    def get_tenant_id(self, tenant_name):
        tenant_api = api.TenantServiceStub(self.channel)
        resp: api.ListTenantsResponse = tenant_api.List(
            api.ListTenantsRequest(search=tenant_name, limit=100),
            metadata=self.metadata,
        )
        if resp.total_count != 1:
            raise ValueError("Missing or duplicated tenant name.")
        tenant_id = resp.result[0].id
        print(f"Tenant ID: {tenant_id}")
        return tenant_id

    def get_application_ids(self, tenant_id):
        application_api = api.ApplicationServiceStub(self.channel)
        resp: api.ListApplicationsResponse = application_api.List(
            api.ListApplicationsRequest(tenant_id=tenant_id, limit=100),
            metadata=self.metadata,
        )
        if resp.total_count == 0:
            raise ValueError("Missing application.")
        app_ids = [app.id for app in resp.result]
        print(f"Application IDs: {app_ids}")
        return app_ids

    def get_dev_euis(self, application_id):
        device_api = api.DeviceServiceStub(self.channel)
        page = 0
        dev_euis = []
        while True:
            offset = 100 * page
            resp: api.ListDevicesResponse = device_api.List(
                api.ListDevicesRequest(
                    application_id=application_id, limit=100, offset=offset
                ),
                metadata=self.metadata,
            )
            dev_euis += [dev.dev_eui for dev in resp.result]
            if 100 * (page + 1) > resp.total_count:
                break
            page += 1
        print(f"Dev EUIs: {dev_euis}")
        return dev_euis

    def create_device_config(self, config_store):
        try:
            self.config_store_api.Create(
                api.CreateDeviceConfigStoreRequest(device_config_store=config_store),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                # Trying to create c for non-existent device
                print(f"ERROR: device not found (id: {config_store.dev_eui})")
                return
            else:
                raise e
        print(f"=> CreateDeviceConfigStore: {config_store}")

    def get_device_config(self, dev_eui):
        try:
            resp: api.GetDeviceConfigStoreResponse = self.config_store_api.Get(
                api.GetDeviceConfigStoreRequest(dev_eui=dev_eui),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                print(f"GetDeviceConfigStore: NOT_FOUND")
                return None
            else:
                raise e
        print(f"GetDeviceConfigStore: {resp.device_config_store}")
        return resp.device_config_store

    def update_device_config(self, config_store):
        self.config_store_api.Update(
            api.UpdateDeviceConfigStoreRequest(device_config_store=config_store),
            metadata=self.metadata,
        )
        print(f"=> UpdateDeviceConfigStore: {config_store}")

    def delete_device_config(self, dev_eui):
        try:
            self.config_store_api.Delete(
                api.DeleteDeviceConfigStoreRequest(dev_eui=dev_eui),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                # Silently continue
                return None
            else:
                raise e

    def list_configured_devices(self, application_id):
        page = 0
        dev_euis = []
        while True:
            offset = 100 * page
            resp: api.ListDeviceConfigStoresResponse = self.config_store_api.List(
                api.ListDeviceConfigStoresRequest(
                    application_id=application_id, limit=100, offset=offset
                ),
                metadata=self.metadata,
            )
            dev_euis += [dev.dev_eui for dev in resp.result]
            if 100 * (page + 1) > resp.total_count:
                break
            page += 1
        print(f"Dev EUIs: {dev_euis}")
        return dev_euis

    def chmask_is_compatible(self, chmask, dev_eui):
        # Check available uplink channels
        resp: api.GetAvailableChannelsResponse = (
            self.config_store_api.GetAvailableUplinkChannels(
                api.GetAvailableChannelsRequest(dev_eui=dev_eui), metadata=self.metadata
            )
        )
        # resp.channels is a MessageMap, to work with it see: https://googleapis.dev/python/protobuf/latest/google/protobuf/internal/containers.html#google.protobuf.internal.containers.MessageMap
        uplink_channels = [k for k in resp.channels.keys()]
        uplink_channels.sort()
        print(f"GetAvailableChannels: {uplink_channels}")
        # Verify configuration feasibility
        if any((ch_id not in uplink_channels for ch_id in chmask)):
            return False
        return True

    def set_chmask_for_device(self, chmask, dev_eui):
        # Validate compatibility with installed channels
        if not self.chmask_is_compatible(chmask, dev_eui):
            print(f"Configuration not compatible (chmask: {chmask})")
            return
        # Create chmask c field
        chmask_config = api.ChMaskConfig(enabled_uplink_channel_indices=chmask)
        device_config_store = self.get_device_config(dev_eui)
        if device_config_store is None:
            # Create device c store from scratch
            device_config_store = api.DeviceConfigStore(
                dev_eui=dev_eui,
                chmask_config=chmask_config,
            )
            self.create_device_config(device_config_store)
        elif device_config_store.chmask_config.enabled_uplink_channel_indices != chmask:
            # Update c store with new chmask field
            device_config_store.chmask_config.CopyFrom(chmask_config)
            self.update_device_config(device_config_store)

    def get_device_config_alignment(self, dev_eui):
        try:
            resp: api.GetConfigStoreAlignmentResponse = (
                self.config_store_api.GetConfigStoreAlignment(
                    api.GetConfigStoreAlignmentRequest(dev_eui=dev_eui),
                    metadata=self.metadata,
                )
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                print(f"GetConfigStoreAlignment: NOT_FOUND")
                # Defaults to True if no configs are present
                return api.ConfigStoreAlignment(chmask_config=True)
            else:
                raise e
        # see: https://stackoverflow.com/questions/61606095/false-boolean-is-not-showing-in-proto3-python
        chmask_config = resp.alignment.chmask_config
        print(f"GetConfigStoreAlignment: chmask_config: {chmask_config}")
        return resp.alignment


if __name__ == "__main__":
    sys.exit(main())
