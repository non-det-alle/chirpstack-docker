import grpc
from chirpstack_api import api
from chirpstack_api.api import DeviceConfigStore
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.message import Message


class NotFoundError(Exception):
    pass


def to_dict(msg: Message) -> dict:
    return MessageToDict(
        msg,
        always_print_fields_with_no_presence=True,
        preserving_proto_field_name=True,
    )


class ChirpStackClient:
    def __init__(self, endpoint: str, token: str) -> None:
        self.endpoint = endpoint
        self.metadata = [("authorization", "Bearer %s" % token)]

    def __enter__(self):
        self.channel = grpc.insecure_channel(self.endpoint)
        self.tenant_api = api.TenantServiceStub(self.channel)
        self.application_api = api.ApplicationServiceStub(self.channel)
        self.device_api = api.DeviceServiceStub(self.channel)
        self.device_profile_api = api.DeviceProfileServiceStub(self.channel)
        self.device_config_store_api = api.DeviceConfigStoreServiceStub(self.channel)
        self.gateway_api = api.GatewayServiceStub(self.channel)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.channel.close()

    def get_tenant_id(self, tenant_name: str) -> str:
        resp: api.ListTenantsResponse = self.tenant_api.List(
            api.ListTenantsRequest(search=tenant_name, limit=100),
            metadata=self.metadata,
        )
        if resp.total_count != 1:
            raise NotFoundError("Missing or duplicated tenant name")
        return resp.result[0].id

    def get_application_ids(self, tenant_id: str) -> list[str]:
        resp: api.ListApplicationsResponse = self.application_api.List(
            api.ListApplicationsRequest(tenant_id=tenant_id, limit=100),
            metadata=self.metadata,
        )
        if resp.total_count == 0:
            return []
        return [app.id for app in resp.result]

    def list_devices(self, application_id) -> list[dict]:
        page = 0
        device_list = []
        while True:
            offset = 100 * page
            resp: api.ListDevicesResponse = self.device_api.List(
                api.ListDevicesRequest(
                    application_id=application_id, limit=100, offset=offset
                ),
                metadata=self.metadata,
            )
            device_list += to_dict(resp)["result"]
            if 100 * (page + 1) > resp.total_count:
                break
            page += 1
        return device_list

    def list_dev_euis(self, application_id: str) -> list[str]:
        return [d["dev_eui"] for d in self.list_devices(application_id)]

    def get_device(self, dev_eui: str) -> dict:
        try:
            resp: api.GetDeviceResponse = self.device_api.Get(
                api.GetDeviceRequest(dev_eui=dev_eui),
                metadata=self.metadata,
            )
            return to_dict(resp)["device"]
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                # Trying to get non-existent device
                print(f"Device not found (id: {dev_eui})")
            raise e

    def set_device_tags(self, dev_eui: str, tags: dict[str, str]) -> None:
        try:
            device = self.get_device(dev_eui) | {"tags": tags}
            self.device_api.Update(
                api.UpdateDeviceRequest(device=ParseDict(device, api.Device())),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                # Trying to update non-existent device
                print(f"Device not found (id: {dev_eui})")
            raise e

    #####################################################################################
    ##                             DEVICE CONFIG STORE API                             ##
    #####################################################################################

    def set_device_config(
        self, dev_eui: str, config_store: api.DeviceConfigStore
    ) -> None:
        try:
            self.device_config_store_api.Set(
                api.SetDeviceConfigStoreRequest(
                    dev_eui=dev_eui, device_config_store=config_store
                ),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                # Trying to set config for non-existent device
                raise NotFoundError(f"Device not found (id: {dev_eui})") from e
            raise e

    def get_device_config(self, dev_eui: str) -> api.DeviceConfigStore:
        try:
            resp: api.GetDeviceConfigStoreResponse = self.device_config_store_api.Get(
                api.GetDeviceConfigStoreRequest(dev_eui=dev_eui),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                raise NotFoundError(f"Config store not found (id: {dev_eui})") from e
            raise e
        return resp.device_config_store

    def delete_device_config(self, dev_eui: str) -> None:
        try:
            self.device_config_store_api.Delete(
                api.DeleteDeviceConfigStoreRequest(dev_eui=dev_eui),
                metadata=self.metadata,
            )
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                # Silently continue
                return
            raise e

    def list_configured_devices(self, application_id: str) -> list[str]:
        page = 0
        dev_euis = []
        while True:
            offset = 100 * page
            resp: api.ListDeviceConfigStoresResponse = (
                self.device_config_store_api.List(
                    api.ListDeviceConfigStoresRequest(
                        application_id=application_id, limit=100, offset=offset
                    ),
                    metadata=self.metadata,
                )
            )
            dev_euis += [dev.dev_eui for dev in resp.result]
            if 100 * (page + 1) > resp.total_count:
                break
            page += 1
        return dev_euis

    def get_device_config_alignment(
        self, dev_eui: str
    ) -> api.GetDeviceConfigAlignmentResponse:
        try:
            resp: api.GetDeviceConfigAlignmentResponse = (
                self.device_config_store_api.GetDeviceConfigAlignment(
                    api.GetDeviceConfigAlignmentRequest(dev_eui=dev_eui),
                    metadata=self.metadata,
                )
            )
        except grpc.RpcError as e:
            match e.code():
                case grpc.StatusCode.NOT_FOUND:
                    # Trying to get config alignment for non existent device or config store
                    raise NotFoundError(e.details()) from e
                case grpc.StatusCode.FAILED_PRECONDITION | grpc.StatusCode.UNAVAILABLE:
                    # Trying to get alignment for unactivated device (either join or manual)
                    # or for unseen activated device after manual activation
                    raise NotFoundError(e.details()) from e
            raise e
        return resp

    def get_device_current_params(
        self, dev_eui: str
    ) -> api.GetDeviceCurrentParamsResponse:
        try:
            resp: api.GetDeviceCurrentParamsResponse = (
                self.device_config_store_api.GetDeviceCurrentParams(
                    api.GetDeviceCurrentParamsRequest(dev_eui=dev_eui),
                    metadata=self.metadata,
                )
            )
        except grpc.RpcError as e:
            match e.code():
                case grpc.StatusCode.NOT_FOUND:
                    # Trying to get params for not existent device
                    raise NotFoundError(f"Device not found (id: {dev_eui})") from e
                case grpc.StatusCode.FAILED_PRECONDITION | grpc.StatusCode.UNAVAILABLE:
                    # Trying to get params for unactivated device (either join or manual)
                    # or for unseen activated device after manual activation
                    raise NotFoundError(e.details()) from e
            raise e
        return resp
