import os

import toml


class Config:
    # static configurations
    with open(os.environ["CHIRPSTACK_API_TOKEN_FILE"], "r") as f:
        CHIRPSTACK_TOKEN = f.readline().rstrip("\n")

    # runtime configurations
    def load(self, path: str):
        c = toml.load(path + "/config.toml")

        self.LOG_LEVEL = c["log"]

        chirpstack = c["chirpstack"]
        self.CHIRPSTACK_ENDPOINT = chirpstack["endpoint"]

        mosquitto = c["mosquitto"]
        self.MOSQUITTO_HOSTNAME = mosquitto["endpoint"].split(":")[0]
        self.MOSQUITTO_PORT = int(mosquitto["endpoint"].split(":")[1])
        self.MOSQUITTO_TOPICS = mosquitto["topics"]
        self.MOSQUITTO_QOS = mosquitto["qos"]

        influxdb = c["influxdb"]
        self.INFLUXDB_URL = "http://" + influxdb["endpoint"]
        self.INFLUXDB_TOKEN = influxdb["token"]
        self.INFLUXDB_ORG = influxdb["org"]
        self.INFLUXDB_BUCKET = influxdb["bucket"]


settings = Config()
