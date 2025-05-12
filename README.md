# A distributed control loop infrastructure for dynamic LoRaWAN management

From [`config-server/src/start.py`](config-server/src/start.py):

```text
            CONTROL LOOP: ARCHITECTURE AND INFORMATION FLOW DIAGRAM                

                       _________________                  _________________
                      |                 |  [3] past      |                 |
                      |  Config Server  |      metrics   | Metrics Storage |
                      |     (this)      | <------------- |   (influxdb2)   |
                      |_________________|                |_________________|
                        ^           ^ \                    ^
                       /             \ \                  /
       [2.a] uplink   /    [4] device \ \ [5] new        / [2.b] uplink
             metrics /         state & \ \    configs   /        metrics
                    /          configs  \ \            /
                   /                     \ \          /
                  /                       \ v        /
       _____________                    ________________
      |             |   [1] uplink     |                |
      |             | ---------------> |                |
      |             | <--------------- |                |
      | MQTT Broker |   [2.a] uplink   | LoRaWAN Server |
      | (mosquitto) |         metrics  |  (chirpstack)  |
      |             |                  |                |
      |             | <--------------- |                |
      |_____________|   [6] downlink   |________________|
         / / | \ \
        /         \
       /           \
      /             \
    GW_1   . . .   GW_n   Gateways

   ~~~ Radio channel ~~~

     ED_1  . . .  ED_m    End Devices


 Communication protocols:
 - MQTT [1], [2.a], [6]
 - REST [2.b], [3]
 - gRPC [4], [5]

 Detailed overview:
 [1] uplink: uplink message received from a gateway being relayed to
     ChirpStack by the MQTT broker.
 [2] uplink metrics: message metadata being distpatched by ChirpStack to the
     Config Server (via MQTT topic subscription [2.a]) and to the Metrics
     Storage (via InfluxDB2 REST API [2.b]).
 [3] past metrics: past uplink records and metrics being queried by the Config
     Server (using the InfluxDB2 REST API and the Flux query language).
     Metrics aggregation can happen either in the Storage using Flux queries,
     or directly in the Config Server (less optimal in distributed settings).
 [4] device state & configs: known parameter state of the device and current
     configuration stored in the server, obtained using ChirpStack's gRPC API.
     Together with traffic metrics, this information should be used in the
     decision making process to evaluate if a needed configuration is
     compatible or needed by the device.
 [5] new config: new configuration for the device sent by the Config Server to
     ChirpStack's device configuration storage (via gRPC API). This should be
     skipped if no configuration is needed.
 [6] downlink: downlink message from ChirpStack to a device. This message is
     relayed by the MQTT broker to the correct gateway, that will send it over
     the Radio channel at the right time to meet the reception window of the
     device. New configurations are inserted in the downlink packet:
     ChirpStack has a dedicated parameter to increase the amount of time it
     will wait before creating the downlink, allowing for configurations to be
     added.
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

This command runs a temporary ChirpStack instance, instantiating a volume used by ChirpStack for persistent storage. This allows us to then generate an API key that will remain valid the next time you run the infrastructure. In case of problems, you can do a full restore by running `docker compose --profile full down` followed by `docker volume rm chirpstack-docker_postgresqldata` to delete persistent storage; just run again the above command to create a new API token.

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

To stop `elora` or the `config-server`, simply `Ctrl-C` in the windows. If anything breaks (*let us know!*) run `docker compose --profile full down` to remove all containers and start from scratch.

### More options

Run the full infrastructure demo in one go with ELoRa for traffic generation:

```sh
docker compose --profile full up -d
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
