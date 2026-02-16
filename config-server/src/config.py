import os

CHIRPSTACK_ENDPOINT = "localhost:8080"
CHIRPSTACK_TENANT = "ELoRa 1"
with open(os.environ["CHIRPSTACK_API_TOKEN_FILE"], "r") as f:
    CHIRPSTACK_TOKEN = f.readline().rstrip("\n")

INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_TOKEN = "token"
INFLUXDB_ORG = "cnam"
INFLUXDB_BUCKET = "chirpstack"
