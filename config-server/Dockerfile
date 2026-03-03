FROM python:3.11.0 AS builder

ARG API_VERSION

RUN git clone --depth=1 -b $API_VERSION https://github.com/nondetalle/chirpstack.git /chirpstack
RUN cd /chirpstack/api/python && make all

RUN python3 -c "import google.protobuf as pb; print(f'protobuf=={pb.__version__}')" > /protobuf.txt

FROM python:alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /chirpstack/api/python/src /chirpstack_api
COPY --from=builder /protobuf.txt /
COPY requirements.txt /

RUN apk add --no-cache tini && \
    cat /protobuf.txt >> /requirements.txt && \
    pip install --no-cache-dir -r /requirements.txt && \
    pip install --no-cache-dir /chirpstack_api

WORKDIR /app

# start.py loaded as volume to facilitate development 
ENTRYPOINT ["/sbin/tini", "-g", "--", "python", "-u", "start.py"]
