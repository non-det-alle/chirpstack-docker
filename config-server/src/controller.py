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


def hard_isolation(cluster_shares: pd.Series) -> pd.Series:
    # grant 1 to each cluster with low share
    cluster_freqs = (cluster_shares <= 1).astype(int)
    available_freqs = len(FREQUENCIES) - cluster_freqs.sum()
    # rescale shares on remaining frequencies
    updated_shares = cluster_shares.mask(cluster_shares <= 1, 0)
    updated_shares = updated_shares / len(FREQUENCIES) * available_freqs
    # allocate interger part of shares
    unserved_share, freqs = np.modf(updated_shares)
    cluster_freqs += freqs
    available_freqs -= int(freqs.sum())
    # allocate fractional parts by magnitude
    for _ in range(available_freqs):
        k = unserved_share.idxmax()
        cluster_freqs[k] += 1
        unserved_share[k] = 0
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
