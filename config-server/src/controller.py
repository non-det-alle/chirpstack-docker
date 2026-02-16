from typing import Any

import numpy as np

from utilities import *

print(CLUSTERS, "\n")

EPOCH = 1 * 60 * 60  # seconds


## manipulate records

records = get_traffic_records(EPOCH)
print("len after get_traffic_records", len(records))
records = clean_traffic_records(records)
print("len after clean_traffic_records", len(records))
records = drop_devices_with_non_unique_sf(records)
print("len after drop_devices_with_non_unique_sf", len(records))
# compute phy payload length
phy_payload_len = get_phy_payload_len(records)
records = records.assign(phy_payload_len=phy_payload_len)
# compute record time on air
time_on_air = get_time_on_air(records)
records = records.assign(time_on_air=time_on_air)
print(records)


## aggregate device metrics

devices = get_devices()
# join SF data to devices
spreading_factors = get_device_sf(records)
devices = devices.join(spreading_factors)
# get best gateway
best_gateway = get_device_best_gateway(records)
devices = devices.join(best_gateway)
# get device traffic metrics
device_metrics = get_device_metrics(records)
devices = devices.join(device_metrics)
# compute measured throughput and scale estimate via pdr
throughput = devices["uplink_bits"] / EPOCH  # bit/s
throughput = throughput / devices["pdr"]
devices = devices.assign(throughput=throughput)
# compute measured offered traffic and scale estimate via pdr
offered_traffic = devices["time_on_air"] / EPOCH  # Erlang
offered_traffic = offered_traffic / devices["pdr"]
devices = devices.assign(offered_traffic=offered_traffic)
print(devices)


### GLOBECOM


def compute_cluster_shares(demands: pd.DataFrame):
    # w_g,c: local traffic demand of a cluster
    clusters = demands.groupby(["gateway_id", "cluster_id"])[["demand"]].sum()
    # sum_c(w_g,c): total local traffic demand
    gateway_demand = clusters.groupby("gateway_id")["demand"].sum()
    clusters = clusters.join(gateway_demand.rename("gateway_demand"))
    # w'_g,c: share of radio frequencies
    freq_share = len(FREQUENCIES) * clusters["demand"] / clusters["gateway_demand"]
    clusters = clusters.assign(freq_share=freq_share)
    return clusters


def hard_isolation(shares: pd.DataFrame) -> dict[Any, int]:
    cluster_shares = shares.to_dict()
    cluster_freqs = {}
    available_freqs = len(FREQUENCIES)
    unserved_share = {k: 0 for k in cluster_shares}
    # grant 1 to every clusters
    for k, v in cluster_shares.items():
        if v <= 1:
            cluster_freqs[k] = 1
            available_freqs -= 1
    freqs_updated = available_freqs
    for k, v in cluster_shares.items():
        if v > 1:
            # rescale on remaining freqs.
            v = v / len(FREQUENCIES) * freqs_updated
            unserved_share[k], freqs = np.modf(v)
            cluster_freqs[k] = int(freqs)
            available_freqs -= cluster_freqs[k]
    while available_freqs > 0:
        k = max(unserved_share, key=unserved_share.get)
        cluster_freqs[k] += 1
        unserved_share[k] = 0
        available_freqs -= 1
    return cluster_freqs


def globecom(devices: pd.DataFrame):
    df = devices.set_index("cluster")  # shallow copy
    # append cluster id and max offered traffic
    df = df.assign(cluster_id=CLUSTERS["id"], max_ot=CLUSTERS["max_ot"])
    # compute device demands for radio resources
    demands = df.assign(demand=(df["throughput"] / df["max_ot"]))
    # compute clusters' frequency shares from device demands
    clusters = compute_cluster_shares(demands)
    # apply frequency share discretization algorithm
    freq_alloc = clusters["freq_share"].groupby("gateway_id").transform(hard_isolation)
    clusters = clusters.assign(freq_alloc=freq_alloc)
    print(clusters)


globecom(devices)
