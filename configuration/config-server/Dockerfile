FROM python:3.9-alpine AS builder

# Install python dependencies
COPY requirements.txt ./
COPY chirpstack/api/python/src ./chirpstack_api
RUN pip install ./chirpstack_api && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.9-alpine

COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages

WORKDIR /usr/src/app

# Configure container startup
CMD ["python", "./start.py"]

# Copy files as late as possible to avoid cache busting during development
COPY start.py ./
