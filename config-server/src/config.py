import os

import toml


class Config:
    # chirpstack defaults
    CHIRPSTACK_ENDPOINT = "localhost:8080"
    CHIRPSTACK_TENANT = "ELoRa 1"

    # influxdb defaults
    INFLUXDB_URL = "http://localhost:8086"
    INFLUXDB_TOKEN = "token"
    INFLUXDB_ORG = "cnam"
    INFLUXDB_BUCKET = "chirpstack"

    # autoload token
    with open(os.environ["CHIRPSTACK_API_TOKEN_FILE"], "r") as f:
        CHIRPSTACK_TOKEN = f.readline().rstrip("\n")

    def load(self, path: str) -> None:
        c = toml.load(path + "/config-server.toml")
        self.CHIRPSTACK_ENDPOINT = c["chirpstack"]["endpoint"]
        self.CHIRPSTACK_TENANT = c["chirpstack"]["tenant_name"]
        self.INFLUXDB_URL = "http://" + c["influxdb"]["endpoint"]
        self.INFLUXDB_TOKEN = c["influxdb"]["token"]
        self.INFLUXDB_ORG = c["influxdb"]["org"]
        self.INFLUXDB_BUCKET = c["influxdb"]["bucket"]


config = Config()
