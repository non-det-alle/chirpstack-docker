from datetime import datetime, timezone, timedelta

import grpc
import chirpstack_api.api as chirpstack_api
import numpy as np

from .unmarshaling import unmarshal_protobuf_message_to_dict
from .config import settings
from .logger import logger


class GRPCStreamReader:
    def __init__(self, on_read):
        self._endpoint = settings.CHIRPSTACK_ENDPOINT
        self._token = settings.CHIRPSTACK_TOKEN

        self._channel = grpc.aio.insecure_channel(self._endpoint)
        self._metadata = [("authorization", f"Bearer {self._token}")]
        self._on_read = on_read
        self._tracking = {}  # dev_eui -> (last seen, count)

        self._internal_api = chirpstack_api.InternalServiceStub(self._channel)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    async def close(self):
        await self._channel.close()

    async def gateway_frames(self, gateway_id):
        req = chirpstack_api.StreamGatewayFramesRequest(gateway_id=gateway_id)
        stream = self._internal_api.StreamGatewayFrames(req, metadata=self._metadata)
        await self._read_forever(gateway_id, stream)

    async def device_frames(self, dev_eui):
        req = chirpstack_api.StreamDeviceFramesRequest(dev_eui=dev_eui)
        stream = self._internal_api.StreamDeviceFrames(req, metadata=self._metadata)
        await self._read_forever(dev_eui, stream)

    async def device_events(self, dev_eui):
        req = chirpstack_api.StreamDeviceEventsRequest(dev_eui=dev_eui)
        stream = self._internal_api.StreamDeviceEvents(req, metadata=self._metadata)
        await self._read_forever(dev_eui, stream)

    async def _read_forever(self, id, stream):
        self._tracking[id] = (datetime.now(timezone.utc), np.uint64(0))

        def obsolete():
            last_seen, count = self._tracking[id]
            now, count = datetime.now(timezone.utc), count + 1
            msg_time = datetime.fromisoformat(log_item["time"])
            assert now > msg_time  # otherwise timezone issues?
            msg_age = now - msg_time
            log_args = (id, count, now - last_seen, msg_age)
            logger.debug("{}: count={}, prev={}, age={}".format(*log_args))
            self._tracking[id] = (now, count)
            return msg_age > timedelta(seconds=1)

        while True:
            try:
                message = await stream.read()
            except grpc.aio.AioRpcError as e:
                logger.error(f"gRPC error: {e.details()}")
                self._tracking.pop(id, None)
                break
            log_item = unmarshal_protobuf_message_to_dict(message)
            if not obsolete():
                await self._on_read(log_item)
