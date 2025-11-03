import tomllib


class Config:
    def load(self, path: str):
        with open(path + "/config.toml", "rb") as f:
            c = tomllib.load(f)

        self.LOG_LEVEL = c["log"]

        redis = c["redis"]
        self.REDIS_URL = "redis://" + redis["endpoint"]
        self.REDIS_STREAM = redis["stream"]

        influxdb = c["influxdb"]
        self.INFLUXDB_URL = "http://" + influxdb["endpoint"]
        self.INFLUXDB_TOKEN = influxdb["token"]
        self.INFLUXDB_ORG = influxdb["org"]
        self.INFLUXDB_BUCKET = influxdb["bucket"]


settings = Config()
