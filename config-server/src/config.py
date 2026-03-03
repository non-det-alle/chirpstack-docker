import os

import toml

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


def load(path: str) -> None:
    c = toml.load(path + "/config-server.toml")

    global CHIRPSTACK_ENDPOINT, CHIRPSTACK_TENANT
    CHIRPSTACK_ENDPOINT = c["chirpstack"]["endpoint"]
    CHIRPSTACK_TENANT = c["chirpstack"]["tenant_name"]

    global INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET
    INFLUXDB_URL = "http://" + c["influxdb"]["endpoint"]
    INFLUXDB_TOKEN = c["influxdb"]["token"]
    INFLUXDB_ORG = c["influxdb"]["org"]
    INFLUXDB_BUCKET = c["influxdb"]["bucket"]
