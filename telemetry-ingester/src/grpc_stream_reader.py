from datetime import datetime, timezone, timedelta

import grpc
import chirpstack_api.api as chirpstack_api
import numpy as np

from .unmarshaling import unmarshal_protobuf_message_to_dict
from .config import settings
from .logger import logger


class GRPCDeviceFrameReader:
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

    def _get_device_frame_stream(self, dev_eui):
        req = chirpstack_api.StreamDeviceFramesRequest(dev_eui=dev_eui)
        return self._internal_api.StreamDeviceFrames(req, metadata=self._metadata)

    async def read_forever(self, dev_eui):
        self._tracking[dev_eui] = (datetime.now(timezone.utc), np.uint64(0))
        stream = self._get_device_frame_stream(dev_eui)

        def obsolete():
            last_seen, count = self._tracking[dev_eui]
            now, count = datetime.now(timezone.utc), count + 1
            msg_time = datetime.fromisoformat(frame_log_item["time"])
            assert now > msg_time  # otherwise timezone issues?
            msg_age = now - msg_time
            log_args = (dev_eui, count, now - last_seen, msg_age)
            logger.debug("dev_eui={}, count={}, prev={}, age={}".format(*log_args))
            self._tracking[dev_eui] = (now, count)
            return msg_age > timedelta(seconds=1)

        while True:
            try:
                message = await stream.read()
            except grpc.aio.AioRpcError as e:
                logger.error(f"gRPC error: {e.details()}")
                self._tracking.pop(dev_eui, None)
                break

            frame_log_item = unmarshal_protobuf_message_to_dict(message)
            if not obsolete():
                await self._on_read(frame_log_item)
