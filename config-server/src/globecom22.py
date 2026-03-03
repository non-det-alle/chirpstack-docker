import pandas as pd
import numpy as np


def globecom22(devices: pd.DataFrame, max_ot: pd.Series, nfreq: int) -> pd.DataFrame:
    df = devices  # shallow copy

    # compute device demands for radio resources
    demand = df["bps"] / df["cluster"].map(max_ot)
    df = df.assign(demand=demand)

    def compute_cluster_shares(devices: pd.DataFrame) -> pd.Series:
        # w_g,c: local traffic demand of a cluster
        cluster_demands = devices.groupby(["gateway_id", "cluster"])["demand"].sum()
        # w'_g,c: normalized share of radio frequencies for gateway cluster
        into_shares = lambda d: d / d.sum() * nfreq
        return cluster_demands.groupby("gateway_id").transform(into_shares)

    # compute clusters' frequency shares from device demands
    freq_share = compute_cluster_shares(df)

    def hard_isolation(freq_share: pd.Series) -> pd.Series:
        # grant 1 to each cluster with low share
        assigned_freq = (freq_share <= 1).astype(int)
        available_freqs = nfreq - assigned_freq.sum()
        # rescale shares on remaining frequencies
        updated_freq_share = freq_share.mask(freq_share <= 1, 0)
        updated_freq_share = updated_freq_share / nfreq * available_freqs
        # allocate interger part of shares
        unserved_freq_share, int_part = np.modf(updated_freq_share)
        assigned_freq += int_part
        available_freqs -= int(int_part.sum())
        # allocate fractional parts by magnitude
        for _ in range(available_freqs):
            cluster_id = unserved_freq_share.idxmax()
            assigned_freq[cluster_id] += 1
            unserved_freq_share[cluster_id] = 0
        return assigned_freq.astype(int)

    # apply frequency share discretization algorithm
    num_freq = freq_share.groupby("gateway_id").transform(hard_isolation)
    df = df.join(num_freq.rename("num_freq"), on=["gateway_id", "cluster"])

    def into_indices(num_freq: pd.Series):
        freq_indices, assigned = [], 0
        for n in num_freq:
            freq_indices.append(list(range(assigned, assigned + n)))
            assigned += n
        return pd.Series(freq_indices, index=num_freq.index)

    # produce chmask for clusters
    chmask = num_freq.groupby("gateway_id").transform(into_indices)
    df = df.join(chmask.rename("chmask"), on=["gateway_id", "cluster"])

    return df
