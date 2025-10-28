from datetime import datetime, timezone, timedelta

import grpc
import chirpstack_api.api as chirpstack_api
from google.protobuf.json_format import MessageToDict

from .config import settings
from .logger import getLogger


class BaseGRPCStreamReader:
    def __init__(self, on_read, log_level: None | str = None):
        self._endpoint = settings.CHIRPSTACK_ENDPOINT
        self._token = settings.CHIRPSTACK_TOKEN

        self._log = getLogger(self.__class__.__name__)
        self._log.setLevel(log_level if log_level else settings.LOG_LEVEL)

        self._channel = grpc.aio.insecure_channel(self._endpoint)
        self._metadata = [("authorization", f"Bearer {self._token}")]
        self._on_read = on_read

        self._internal_api = chirpstack_api.InternalServiceStub(self._channel)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    async def close(self):
        await self._channel.close()

    async def _read_forever(self, stream):
        async def _read_stream():
            return MessageToDict(
                await stream.read(),
                always_print_fields_with_no_presence=True,
                preserving_proto_field_name=True,
            )

        async def _first_message():
            # on stream instantiation, chirpstack always fetches up to 10
            # logs (as this was meant for UI display) but we want the actual
            # latest log(s) that triggered the server-side send

            def _message_is_obsolete():
                msg_time = datetime.fromisoformat(message["time"])
                now = datetime.now(timezone.utc)
                assert now > msg_time  # otherwise timezone issues?
                msg_age = now - msg_time
                self._log.debug(f"msg_age={msg_age}")
                # chirpstack checks for new logs every 1 second
                return msg_age > timedelta(seconds=1)

            # consume out-of-date logs
            message = await _read_stream()
            while _message_is_obsolete():
                message = await _read_stream()
            return message

        try:
            log_item = await _first_message()
            while True:
                await self._on_read(log_item)
                log_item = await _read_stream()
        except grpc.aio.AioRpcError as e:
            self._log.error(f"gRPC error: {e.details()}")


class GRPCDeviceFramesReader(BaseGRPCStreamReader):
    async def read(self, dev_eui):
        req = chirpstack_api.StreamDeviceFramesRequest(dev_eui=dev_eui)
        kwargs = {"metadata": self._metadata, "timeout": 86400}
        stream = self._internal_api.StreamDeviceFrames(req, **kwargs)
        await self._read_forever(stream)


class GRPCDeviceEventsReader(BaseGRPCStreamReader):
    async def read(self, dev_eui):
        req = chirpstack_api.StreamDeviceEventsRequest(dev_eui=dev_eui)
        kwargs = {"metadata": self._metadata, "timeout": 86400}
        stream = self._internal_api.StreamDeviceEvents(req, **kwargs)
        await self._read_forever(stream)
