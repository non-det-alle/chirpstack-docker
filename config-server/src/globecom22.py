import pandas as pd
import numpy as np

from utilities import CLUSTERS, FREQUENCIES


def compute_cluster_shares(devices: pd.DataFrame):
    # w_g,c: local traffic demand of a cluster
    clusters = devices.groupby(["gateway_id", "cluster_id"])[["demand"]].sum()
    # sum_c(w_g,c): total local traffic demand
    gateway_demand = clusters.groupby("gateway_id")["demand"].sum()
    clusters = clusters.join(gateway_demand.rename("gateway_demand"))
    # w'_g,c: share of radio frequencies
    freq_share = len(FREQUENCIES) * clusters["demand"] / clusters["gateway_demand"]
    clusters = clusters.assign(freq_share=freq_share)
    return clusters


def hard_isolation(cluster_freq_share: pd.Series) -> pd.Series:
    # grant 1 to each cluster with low share
    cluster_freq_num = (cluster_freq_share <= 1).astype(int)
    available_freqs = len(FREQUENCIES) - cluster_freq_num.sum()
    # rescale shares on remaining frequencies
    updated_freq_share = cluster_freq_share.mask(cluster_freq_share <= 1, 0)
    updated_freq_share = updated_freq_share / len(FREQUENCIES) * available_freqs
    # allocate interger part of shares
    unserved_freq_share, int_part = np.modf(updated_freq_share)
    cluster_freq_num += int_part
    available_freqs -= int(int_part.sum())
    # allocate fractional parts by magnitude
    for _ in range(available_freqs):
        cluster_id = unserved_freq_share.idxmax()
        cluster_freq_num[cluster_id] += 1
        unserved_freq_share[cluster_id] = 0
    return cluster_freq_num.astype(int)


def globecom22(devices: pd.DataFrame, debug=False) -> pd.DataFrame:
    df = devices  # shallow copy

    # append cluster id and max offered traffic
    df = df.reset_index().set_index("cluster")
    df = df.assign(cluster_id=CLUSTERS["id"], max_ot=CLUSTERS["max_ot"])
    # compute device demands for radio resources
    df = df.assign(demand=(df["throughput"] / df["max_ot"]))

    # compute clusters' frequency shares from device demands
    clusters = compute_cluster_shares(df)

    # apply frequency share discretization algorithm
    freq_num = clusters["freq_share"].groupby("gateway_id").transform(hard_isolation)
    clusters = clusters.assign(freq_num=freq_num)

    def to_indices(cluster_freq_num: pd.Series):
        cluster_freq_indices, assigned_freqs = [], 0
        for freq_num in cluster_freq_num:
            first, last = assigned_freqs, assigned_freqs + int(freq_num)
            cluster_freq_indices.append(list(range(first, last)))
            assigned_freqs = last
        return pd.Series(cluster_freq_indices, index=cluster_freq_num.index)

    # produce chmask for clusters
    chmask = clusters["freq_num"].groupby("gateway_id").transform(to_indices)
    clusters = clusters.assign(chmask=chmask)
    if debug:
        print(clusters)

    # append configs to devices
    df = df.set_index(["gateway_id", "cluster_id"])
    df = df.join(clusters[["freq_num", "chmask"]])
    df = df.reset_index().set_index("dev_eui")

    return df
