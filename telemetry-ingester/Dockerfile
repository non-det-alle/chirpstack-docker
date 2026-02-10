FROM python:3.14-alpine3.22 AS builder

ARG API_VERSION

COPY lorawan-decoder/ lorawan-decoder/

RUN apk add --no-cache build-base && \
    sed -i 's/^lrwn = { tag = "[^"]*/lrwn = { tag = "'$API_VERSION'/' lorawan-decoder/Cargo.toml && \
    pip wheel -v -w wheels/ lorawan-decoder/

FROM python:3.14-alpine3.22

ARG API_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    apk add --no-cache tini libgcc && \
    pip install --no-cache-dir /wheels/*.whl && \
    sed -i s/chirpstack-api==.*/chirpstack-api==${API_VERSION}/ requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY start.py .

ENTRYPOINT ["/sbin/tini", "-g", "--", "python", "start.py"]
