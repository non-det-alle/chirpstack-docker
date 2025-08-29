import asyncio

import grpc
import chirpstack_api.api as chirpstack_api

from .config import settings
from .logger import logger


def paginate(page_size=100):
    def decorator(grpc_list_func):
        async def wrapped_function(*args, **kwargs):
            kwargs["limit"] = page_size
            resp = await grpc_list_func(*args, **kwargs)
            while len(resp.result) < resp.total_count:
                kwargs["offset"] = len(resp.result)
                tmp = await grpc_list_func(*args, **kwargs)
                resp.result.extend(tmp.result)
            return resp

        return wrapped_function

    return decorator


class GRPCDiscoveryService:
    def __init__(self, on_discovery):
        self._endpoint = settings.CHIRPSTACK_ENDPOINT
        self._token = settings.CHIRPSTACK_TOKEN

        self._channel = grpc.aio.insecure_channel(self._endpoint)
        self._metadata = [("authorization", f"Bearer {self._token}")]
        self._on_discovery = on_discovery
        self._task_group: asyncio.TaskGroup
        self._main_task: asyncio.Task
        self._discovered = {}

        self._tenant_api = chirpstack_api.TenantServiceStub(self._channel)
        self._application_api = chirpstack_api.ApplicationServiceStub(self._channel)
        self._device_api = chirpstack_api.DeviceServiceStub(self._channel)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()

    async def close(self):
        await self._channel.close()

    @paginate()
    async def _list_tenants(self, **kwargs) -> chirpstack_api.ListTenantsResponse:
        req = chirpstack_api.ListTenantsRequest(**kwargs)
        return await self._tenant_api.List(req, metadata=self._metadata)

    @paginate()
    async def _list_applications(
        self, tenant_id, **kwargs
    ) -> chirpstack_api.ListApplicationsResponse:
        req = chirpstack_api.ListApplicationsRequest(tenant_id=tenant_id, **kwargs)
        return await self._application_api.List(req, metadata=self._metadata)

    @paginate(page_size=1000)
    async def _list_devices(
        self, application_id, **kwargs
    ) -> chirpstack_api.ListDevicesResponse:
        req = chirpstack_api.ListDevicesRequest(application_id=application_id, **kwargs)
        return await self._device_api.List(req, metadata=self._metadata)

    async def _loop_forever(self):
        while True:
            try:
                devices = {
                    d.dev_eui
                    for t in (await self._list_tenants()).result
                    for a in (await self._list_applications(t.id)).result
                    for d in (await self._list_devices(a.id)).result
                }
                removed = self._discovered.keys() - devices
                added = devices - self._discovered.keys()
                for dev_eui in removed:
                    self._discovered[dev_eui].cancel()
                for dev_eui in added:
                    self._register(dev_eui)
                await asyncio.sleep(60)
            except Exception as e:
                logger.exception(e)

    def _register(self, id):
        def unregister(_):
            logger.info(f"Removing device {id}")
            self._discovered.pop(id, None)

        logger.info(f"Registering device {id}")
        coroutine = self._on_discovery(id)
        task = self._task_group.create_task(coroutine)  # run concurrently
        task.add_done_callback(unregister)
        self._discovered[id] = task

    async def start(self):
        async with asyncio.TaskGroup() as tg:
            self._task_group = tg
            logger.info(f"Starting discovery service...")
            coroutine = self._loop_forever()
            self.main_task = tg.create_task(coroutine)
