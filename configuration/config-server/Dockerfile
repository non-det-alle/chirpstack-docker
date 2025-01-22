FROM python:3.11.0 AS builder

ENV PROJECT_PATH=/chirpstack/api

RUN git clone --depth=1 https://github.com/protocolbuffers/protobuf.git /protobuf
RUN git clone --depth=1 https://github.com/googleapis/googleapis.git /googleapis

COPY chirpstack/api $PROJECT_PATH
WORKDIR $PROJECT_PATH

RUN sh -c "cd python && make all"

FROM python:alpine

COPY --from=builder /chirpstack/api/python/src /chirpstack_api

COPY requirements.txt ./
RUN pip install --no-cache-dir /chirpstack_api && \
    pip install --no-cache-dir -r requirements.txt

WORKDIR /usr/src/app

# Configure container startup
CMD ["python", "-u", "start.py", "-c", "config-server.toml"]

# start.py must be loaded as a volume to facilitate development 
