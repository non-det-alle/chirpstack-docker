FROM python:3.11.0 AS builder

ARG VERSION

RUN git clone --depth=1 https://github.com/protocolbuffers/protobuf.git /protobuf
RUN git clone --depth=1 https://github.com/googleapis/googleapis.git /googleapis

RUN git clone --depth=1 -b $VERSION https://github.com/non-det-alle/chirpstack.git /chirpstack
RUN cd /chirpstack/api/python && make all

FROM python:alpine

COPY --from=builder /chirpstack/api/python/src /chirpstack_api
COPY requirements.txt ./

RUN apk add --no-cache tini && \
    pip install --no-cache-dir /chirpstack_api && \
    pip install --no-cache-dir -r requirements.txt

WORKDIR /usr/src/app

# start.py loaded as volume to facilitate development 
ENTRYPOINT ["/sbin/tini", "-g", "--", "python", "-u", "start.py"]
