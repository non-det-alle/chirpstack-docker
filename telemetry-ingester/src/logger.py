import logging


class MicroSecondFormatter(logging.Formatter):
    # Workaround until https://github.com/python/cpython/issues/90450 is fixed
    def formatTime(self, record, datefmt=None):
        record.usecs = 100_000 * (record.created % 1)
        return super().formatTime(record, datefmt=datefmt)


def getLogger(name="telemetry-ingester") -> logging.Logger:
    formatter = MicroSecondFormatter(
        fmt="%(asctime)s.%(usecs)06.0fZ [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

    return logger


global_logger = getLogger()
