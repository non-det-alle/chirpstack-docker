import redis
import chirpstack_api.stream as chirpstack_api
import google.protobuf.json_format as protobuf
from lorawan_decoder import phy_payload

from .config import settings
from .logger import getLogger


class RedisReader:
    def __init__(self, on_read, log_level: None | str = None):
        self._url = settings.REDIS_URL
        self._stream = settings.REDIS_STREAM

        self._log = getLogger(self.__class__.__name__)
        self._log.setLevel(log_level if log_level else settings.LOG_LEVEL)

        self._client = redis.from_url(self._url)
        self._on_read = on_read
        self._last_id = "0"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._client.close()

    def _handle_stream(self, k, v):
        if k == "up":
            message = chirpstack_api.UplinkFrameLog()
        elif k == "down":
            message = chirpstack_api.DownlinkFrameLog()
        else:
            raise KeyError("Unexpected key in frame-log stream")
        message.ParseFromString(v)
        frame_log = protobuf.MessageToDict(
            message,
            always_print_fields_with_no_presence=True,
            preserving_proto_field_name=True,
        )
        return {
            "time": frame_log["time"],
            "log_id": self._last_id,
            "dev_eui": frame_log["dev_eui"],
            "phy_payload": phy_payload.from_bytes(
                message.phy_payload,
                message.plaintext_f_opts,
                message.plaintext_frm_payload,
            ),
            "tx_info": frame_log["tx_info"],
            "rx_info": frame_log.pop("rx_info", None),
        }

    def _read_stream(self):
        streams = {self._stream: self._last_id}
        reply = self._client.xread(streams, block=0)
        self._log.debug(f"Redis XREAD reply: {reply}")
        for id, entry in reply[0][1]:
            self._last_id = id.decode()
            for k, v in entry.items():
                yield self._handle_stream(k.decode(), v)

    def read_forever(self):
        self._log.info(f"Starting service for {self._stream} on {self._url}")
        while True:
            try:
                logs = list(self._read_stream())
                self._log.debug(f"Frame logs: {logs}")
                self._on_read(logs)
            except Exception as e:
                self._log.error(f"Redis stream read error: {e}")
