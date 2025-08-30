import asyncio

import grpc
import chirpstack_api.api as chirpstack_api

from .config import settings
from .logger import logger


def paginate(page_size=100):
    def decorator(grpc_list_func):
        async def wrapped_function(*args, **kwargs):
            kwargs |= {"limit": page_size}
            resp = await grpc_list_func(*args, **kwargs)
            offsets = list(range(page_size, resp.total_count, page_size))
            rpcs = [grpc_list_func(*args, **(kwargs | {"offset": o})) for o in offsets]
            [resp.result.extend(msg.result) for msg in await asyncio.gather(*rpcs)]
            return resp

        return wrapped_function

    return decorator


class BaseGRPCDiscoveryService:
    def __init__(self, on_discovery):
        self._endpoint = settings.CHIRPSTACK_ENDPOINT
        self._token = settings.CHIRPSTACK_TOKEN

        self._channel = grpc.aio.insecure_channel(self._endpoint)
        self._metadata = [("authorization", f"Bearer {self._token}")]
        self._on_discovery = on_discovery
        self._task_group: asyncio.TaskGroup
        self._main_task: asyncio.Task
        self._discovered = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()

    async def close(self):
        await self._channel.close()

    def _register(self, id):
        def unregister(_):
            logger.info(f"Removing task for {id}")
            self._discovered.pop(id, None)

        logger.info(f"Registering task for {id}")
        coroutine = self._on_discovery(id)
        task = self._task_group.create_task(coroutine)  # run concurrently
        task.add_done_callback(unregister)
        self._discovered[id] = task

    def _unregister(self, id):
        self._discovered[id].cancel()

    def _update_tasks(self, new):
        removed = self._discovered.keys() - new
        added = new - self._discovered.keys()
        [self._unregister(id) for id in removed]
        [self._register(id) for id in added]

    async def _get_ids(self):
        """Overridden in child classes"""
        return set()

    async def _loop_forever(self, poll_interval=30):
        while True:
            try:
                current_ids = await self._get_ids()
                self._update_tasks(current_ids)
                await asyncio.sleep(poll_interval)
            except Exception as e:
                logger.exception(e)

    async def start(self, poll_interval=30):
        async with asyncio.TaskGroup() as tg:
            self._task_group = tg
            logger.info(f"Starting discovery service...")
            coroutine = self._loop_forever(poll_interval)
            self.main_task = tg.create_task(coroutine)


### See, grpc_stream_reader.py

# class GRPCGatewayDiscoveryService(BaseGRPCDiscoveryService):
#     def __init__(self, on_discovery):
#         super().__init__(on_discovery)

#         self._gateway_api = chirpstack_api.GatewayServiceStub(self._channel)

#     @paginate()
#     async def _list_gateways(self, **kwargs):
#         req = chirpstack_api.ListGatewaysRequest(**kwargs)
#         return await self._gateway_api.List(req, metadata=self._metadata)

#     async def _get_ids(self):
#         gateways = (await self._list_gateways()).result
#         return {g.gateway_id for g in gateways}


class GRPCDeviceDiscoveryService(BaseGRPCDiscoveryService):
    def __init__(self, on_discovery):
        super().__init__(on_discovery)

        self._tenant_api = chirpstack_api.TenantServiceStub(self._channel)
        self._application_api = chirpstack_api.ApplicationServiceStub(self._channel)
        self._device_api = chirpstack_api.DeviceServiceStub(self._channel)

    @paginate()
    async def _list_tenants(self, **kwargs):
        req = chirpstack_api.ListTenantsRequest(**kwargs)
        return await self._tenant_api.List(req, metadata=self._metadata)

    @paginate()
    async def _list_applications(self, tenant_id, **kwargs):
        req = chirpstack_api.ListApplicationsRequest(tenant_id=tenant_id, **kwargs)
        return await self._application_api.List(req, metadata=self._metadata)

    @paginate(page_size=1000)
    async def _list_devices(self, application_id, **kwargs):
        req = chirpstack_api.ListDevicesRequest(application_id=application_id, **kwargs)
        return await self._device_api.List(req, metadata=self._metadata)

    async def _get_ids(self):
        return {
            d.dev_eui
            for t in (await self._list_tenants()).result
            for a in (await self._list_applications(t.id)).result
            for d in (await self._list_devices(a.id)).result
        }
