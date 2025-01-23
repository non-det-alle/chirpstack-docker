# A distributed control loop infrastructure for dynamic LoRaWAN management

From [`configuration/config-server/start.py`](configuration/config-server/start.py):

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
                  /                       \ ⌄        /
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

## Running

Generate ChirpStack api token by running in the repo's root:

```sh
docker compose run --rm chirpstack -c /etc/chirpstack create-api-key --name config-store | sed -n 's/^token: //p' > .env.chirpstack-api-token
```

Then run the full infrastructure demo with ELoRa for traffic generation:

```sh
docker compose --profile full up -d
```

Follow specific logs with:

```sh
docker compose logs -f [SERVICE]
```

where `SERVICE` is the name specified in [`docker-compose.yml`](docker-compose.yml) for a container. Most insightful are `chirpstack`, `elora` and `config-server`.

<!-- # ChirpStack Docker example

This repository contains a skeleton to setup the [ChirpStack](https://www.chirpstack.io)
open-source LoRaWAN Network Server (v4) using [Docker Compose](https://docs.docker.com/compose/).

**Note:** Please use this `docker-compose.yml` file as a starting point for testing
but keep in mind that for production usage it might need modifications.

## Directory layout

* `docker-compose.yml`: the docker-compose file containing the services
* `configuration/chirpstack`: directory containing the ChirpStack configuration files
* `configuration/chirpstack-gateway-bridge`: directory containing the ChirpStack Gateway Bridge configuration
* `configuration/mosquitto`: directory containing the Mosquitto (MQTT broker) configuration
* `configuration/postgresql/initdb/`: directory containing PostgreSQL initialization scripts

## Configuration

This setup is pre-configured for all regions. You can either connect a ChirpStack Gateway Bridge
instance (v3.14.0+) to the MQTT broker (port 1883) or connect a Semtech UDP Packet Forwarder.
Please note that:

* You must prefix the MQTT topic with the region.
  Please see the region configuration files in the `configuration/chirpstack` for a list
  of topic prefixes (e.g. eu868, us915_0, au915_0, as923_2, ...).
* The protobuf marshaler is configured.

This setup also comes with two instances of the ChirpStack Gateway Bridge. One
is configured to handle the Semtech UDP Packet Forwarder data (port 1700), the
other is configured to handle the Basics Station protocol (port 3001). Both
instances are by default configured for EU868 (using the `eu868` MQTT topic
prefix).

### Reconfigure regions

ChirpStack has at least one configuration of each region enabled. You will find
the list of `enabled_regions` in `configuration/chirpstack/chirpstack.toml`.
Each entry in `enabled_regions` refers to the `id` that can be found in the
`region_XXX.toml` file. This `region_XXX.toml` also contains a `topic_prefix`
configuration which you need to configure the ChirpStack Gateway Bridge
UDP instance (see below).

#### ChirpStack Gateway Bridge (UDP)

Within the `docker-compose.yml` file, you must replace the `eu868` prefix in the
`INTEGRATION__..._TOPIC_TEMPLATE` configuration with the MQTT `topic_prefix` of
the region you would like to use (e.g. `us915_0`, `au915_0`, `in865`, ...).

#### ChirpStack Gateway Bridge (Basics Station)

Within the `docker-compose.yml` file, you must update the configuration file
that the ChirpStack Gateway Bridge instance must used. The default is
`chirpstack-gateway-bridge-basicstation-eu868.toml`. For available
configuration files, please see the `configuration/chirpstack-gateway-bridge`
directory.

# Data persistence

PostgreSQL and Redis data is persisted in Docker volumes, see the `docker-compose.yml`
`volumes` definition.

## Requirements

Before using this `docker-compose.yml` file, make sure you have [Docker](https://www.docker.com/community-edition)
installed.

## Usage

To start the ChirpStack simply run:

```bash
$ docker compose up
```

After all the components have been initialized and started, you should be able
to open <http://localhost:8080/> in your browser.

##

The example includes the [ChirpStack REST API](https://github.com/chirpstack/chirpstack-rest-api).
You should be able to access the UI by opening <http://localhost:8090> in your browser.

**Note:** It is recommended to use the [gRPC](https://www.chirpstack.io/docs/chirpstack/api/grpc.html)
interface over the [REST](https://www.chirpstack.io/docs/chirpstack/api/rest.html) interface. -->
