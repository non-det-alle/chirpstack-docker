import grpc
from chirpstack_api import api
from google.protobuf.json_format import MessageToDict


class ChirpStackClient:
    def __init__(self, endpoint: str, token: str) -> None:
        self.endpoint = endpoint
        self.metadata = [("authorization", "Bearer %s" % token)]

    def __enter__(self):
        self.channel = grpc.insecure_channel(self.endpoint)
        self.config_store_api = api.DeviceConfigStoreServiceStub(self.channel)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.channel.close()

    def get_tenant_id(self, tenant_name: str) -> str:
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

    def get_application_ids(self, tenant_id: str) -> list[str]:
        application_api = api.ApplicationServiceStub(self.channel)
        resp: api.ListApplicationsResponse = application_api.List(
            api.ListApplicationsRequest(tenant_id=tenant_id, limit=100),
            metadata=self.metadata,
        )
        if resp.total_count == 0:
            return []
        app_ids = [app.id for app in resp.result]
        print(f"Application IDs: {app_ids}")
        return app_ids

    def get_dev_euis(self, application_id: str) -> list[str]:
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

    def set_device_config(self, config_store: api.DeviceConfigStore) -> None:
        try:
            self.config_store_api.Set(
                api.SetDeviceConfigStoreRequest(device_config_store=config_store),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                # Trying to set config for non-existent device
                print(f"ERROR: device not found (id: {config_store.dev_eui})")
            raise e
        print(f"=> SetDeviceConfigStore: {config_store}")

    def get_device_config(self, dev_eui: str) -> api.DeviceConfigStore | None:
        try:
            resp: api.GetDeviceConfigStoreResponse = self.config_store_api.Get(
                api.GetDeviceConfigStoreRequest(dev_eui=dev_eui),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                print(f"GetDeviceConfigStore: NOT_FOUND")
                return
            raise e
        print(f"GetDeviceConfigStore: {resp.device_config_store}")
        return resp.device_config_store

    def delete_device_config(self, dev_eui: str) -> None:
        try:
            self.config_store_api.Delete(
                api.DeleteDeviceConfigStoreRequest(dev_eui=dev_eui),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                # Silently continue
                return
            raise e
        print(f"DeleteDeviceConfigStore: {dev_eui}")

    def list_configured_devices(self, application_id: str) -> list[str]:
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
        print(f"Dev EUIs with configs: {dev_euis}")
        return dev_euis

    def get_device_config_alignment(self, dev_eui: str) -> api.ConfigStoreAlignment:
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
            raise e
        # Prints nothing if false, see: https://stackoverflow.com/questions/61606095/false-boolean-is-not-showing-in-proto3-python
        align_dict = MessageToDict(
            resp.alignment, always_print_fields_with_no_presence=True
        )
        print(f"GetConfigStoreAlignment: {align_dict}")
        return resp.alignment

    def get_device_available_uplink_channels(
        self, chmask: list[int], dev_eui: str
    ) -> list[int]:
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
        return uplink_channels

    def is_chmask_compatible(self, chmask: list[int], dev_eui: str) -> bool:
        uplink_channels = self.get_device_available_uplink_channels(chmask, dev_eui)
        # Verify configuration feasibility
        if any((ch_id not in uplink_channels for ch_id in chmask)):
            return False
        return True

    def set_chmask_for_device(self, chmask: list[int], dev_eui: str) -> None:
        # Create chmask config field
        self.set_device_config(
            api.DeviceConfigStore(
                dev_eui=dev_eui,
                chmask_config=api.ChMaskConfig(
                    enabled_uplink_channel_indices=chmask,
                ),
            )
        )

    def is_device_chmask_aligned(self, dev_eui: str) -> bool:
        return self.get_device_config_alignment(dev_eui).chmask_config

