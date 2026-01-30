# A distributed control loop infrastructure for dynamic LoRaWAN management

```text
            CONTROL LOOP: ARCHITECTURE AND INFORMATION FLOW DIAGRAM                

                     _________________                  _________________
                    |                 |  [2] past      |                 |
                    |  Config Server  |      metrics   | Metrics Storage |
                    |     (this)      | <------------- |    (influxdb)   |
                    |_________________|                |_________________|
                        ^ /                                ^
                       / /                                /
        [3] device    / / [4] new device                 / [1.b] uplink &
            state &  / /      configs                   /        downlink
            configs / /                                /         frame logs
                   / /                                /
                  / v                                /
       ________________                      ____________________  
      |                |                    |                    |
      |                | -----------------> | Telemetry Ingester |
      |                |  [1.a] uplink &    |       (this)       |
      | LoRaWAN Server |        downlink    |____________________|
      |  (chirpstack)  |        frame logs
      |                |
      |                |
      |________________|
           / / | \ \
          /         \
         /           \
        /             \
      GW_1   . . .   GW_n   Gateways
  
     ~~~ Radio channel ~~~
  
       ED_1  . . .  ED_m    End Devices


 Communication protocols:
 - RESP [1.a]
 - REST [1.b], [2]
 - gRPC [3], [4]

 Detailed overview:
 [1] uplink & downlink frame logs: packet metadata streamed from ChirpStack's
     logging backend (via REdis Serialization Protocol (RESP) [1.a]) and
     forwarded to the Metrics Storage function (via InfluxDB REST API [1.b]) by
     the Telemetry Ingester.
 [2] past metrics: past records and metrics being queried by the Config Server
     (using the InfluxDB REST API and the Flux query language). Metrics
     aggregation can happen either in the Storage using Flux queries, or
     directly in the Config Server (less optimal in distributed settings).
 [4] device state & configs: known parameter state of the device and current
     configuration stored in the server, obtained using ChirpStack's gRPC API.
     Together with traffic metrics, this information should be used in the
     decision making process to evaluate if a desired configuration is
     compatible with or needed for the device.
 [4] new device config: new configuration for the device sent by the Config
     Server to ChirpStack's device configuration storage (via gRPC API).
```

## Prerequisites

Make sure you have docker and docker-compose installed. This implementation can be run fully inside docker if you have any problem with networking on your machine (exposing ports on localhost, etc.)

Clone the repo:

```sh
git clone https://github.com/non-det-alle/chirpstack-docker.git
```

Generate ChirpStack API token by running in the repo's root:

```sh
docker compose up chirpstack -d && sleep 1 && docker compose run --rm chirpstack -c /etc/chirpstack create-api-key --name config-store | sed -n 's/^token: //p' > .env.chirpstack-api-token && docker compose down
```

This command runs a temporary ChirpStack instance, instantiating a volume used by ChirpStack for persistent storage. This allows us to then generate an API key that will remain valid the next time you run the infrastructure. In case of problems, you can do a full restore by running `docker compose --profile all down` followed by `docker volume rm chirpstack-docker_postgresqldata` to delete persistent storage; just run again the above command to create a new API token.

## Running

> This is a suggested workflow to showcase the capabilities of the `config-server` function.
>
> Checkout [docker compose documentation](https://docs.docker.com/compose/intro/compose-application-model/) for more.

Run the infrastructure (minus the `config-server`) in the background with:

```sh
docker compose up -d
```

Now you can:

* `docker compose logs -f chirpstack`: Follow `chirpstack` logs to check what the network server is doing
* `docker compose up elora`: In a second terminal, run the emulated access network using ELoRa
* `docker compose up config-server`: In a third terminal, run the configuration server

To stop `elora` or the `config-server`, simply `Ctrl-C` in the windows. If anything breaks (*let us know!*) run `docker compose --profile all down` to remove all containers and start from scratch.

### More options

Run the full infrastructure demo in one go with ELoRa for traffic generation:

```sh
docker compose --profile all up -d
```

Then, follow specific logs with:

```sh
docker compose logs -f [SERVICE]
```

where `SERVICE` is the name specified in [`docker-compose.yml`](docker-compose.yml) for a container. Most insightful are `chirpstack`, `elora` and `config-server`.

## Development

Implement your algorithm and other changes in [`config-server/src`](config-server/src). You can find the source for this demo in the file `start.py`. The `src` directory is loaded as a shared volume in the container, so changes can be loaded by simply runnning `docker compose up config-server` again. Changing language will require you to write your own `Dockerfile` to build the container environment.

## More documentation

* this config-server API example: [docs/API.md](docs/API.md)
* chirpstack gRPC API: <https://github.com/non-det-alle/chirpstack/tree/config-store/api/proto>
* chirpstack-docker: <https://github.com/chirpstack/chirpstack-docker>
* elora: <https://github.com/Orange-OpenSource/elora>
* ns-3: <https://www.nsnam.org/docs/release/3.43/tutorial/html/index.html>
* Flux query language: <https://docs.influxdata.com/flux/v0/>
