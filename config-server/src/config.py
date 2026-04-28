import os

import toml


class Config:
    # chirpstack defaults
    CHIRPSTACK_ENDPOINT: str = "localhost:8080"
    CHIRPSTACK_TENANTS: list[str] = []

    # influxdb defaults
    INFLUXDB_URL: str = "http://localhost:8086"
    INFLUXDB_TOKEN: str = "token"
    INFLUXDB_ORG: str = "cnam"
    INFLUXDB_BUCKET: str = "chirpstack"

    # autoload token
    with open(os.environ["CHIRPSTACK_API_TOKEN_FILE"], "r") as f:
        CHIRPSTACK_TOKEN: str = f.readline().rstrip("\n")

    def load(self, path: str) -> None:
        c = toml.load(path + "/config-server.toml")
        self.CHIRPSTACK_ENDPOINT = c["chirpstack"]["endpoint"]
        self.CHIRPSTACK_TENANTS = c["chirpstack"]["tenant_names"]
        self.INFLUXDB_URL = "http://" + c["influxdb"]["endpoint"]
        self.INFLUXDB_TOKEN = c["influxdb"]["token"]
        self.INFLUXDB_ORG = c["influxdb"]["org"]
        self.INFLUXDB_BUCKET = c["influxdb"]["bucket"]


config = Config()
