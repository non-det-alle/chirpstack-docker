FROM python:3.11.0 AS builder

ARG API_VERSION

RUN git clone --depth=1 -b $API_VERSION https://github.com/non-det-alle/chirpstack.git
RUN cd chirpstack/api/python && make all

RUN python3 -c "import google.protobuf as pb; print(f'protobuf=={pb.__version__}')" > protobuf.txt

FROM python:alpine3.22

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
COPY --from=builder chirpstack/api/python/src/ chirpstack_api/
COPY --from=builder protobuf.txt .

RUN apk add --no-cache tini && \
    cat protobuf.txt >> requirements.txt && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir chirpstack_api/ && \
    rm -rf chirpstack_api/ protobuf.txt

COPY src/ src/

ENTRYPOINT ["/sbin/tini", "-g", "--", "python", "-m", "src.mqtt_to_influxdb"]
