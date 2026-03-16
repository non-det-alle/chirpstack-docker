import time

import pandas as pd
import numpy as np
import scipy.stats as sps

from . import utilities as ut

LOOKBACK_HORIZON = 1 * 60 * 60  # seconds

PVALUE_THRESHOLD = 0.05

CONFIG_DECAY_THRESHOLD = 1 * 60 * 60  # seconds


# mutable global table
DECAYING = pd.DataFrame()


def run(ns: ut.NS, db: ut.DB):
    # load devices
    devices = ut.get_devices(ns)[["name"]]
    dev_euis = list(devices.index)

    # load traffic records
    records = ut.get_traffic_records(db, dev_euis, LOOKBACK_HORIZON)
    records = ut.clean_traffic_records(records)

    # load frequencies from server device session
    frequencies = ut.get_freq_indices(ns, dev_euis)
    # compute and join freq test results from records
    freq_stats = device_freq_nrecv_ttest(frequencies, records)
    frequencies = frequencies.join(freq_stats)
    print(frequencies)

    # (optional) aggregate device traffic metrics
    # packet_toa_metrics = ut.get_packet_toa_metrics(records)
    # records = records.join(packet_toa_metrics)
    device_sfs = ut.get_device_sf(records)
    devices = devices.join(device_sfs)
    # device_toa_metrics = ut.get_device_toa_metrics(records)
    # devices = devices.join(device_toa_metrics)
    device_pdr_metrics = ut.get_device_pdr_metrics(records)
    devices = devices.join(device_pdr_metrics)

    # generate chmask configs
    enabled = get_enabled_with_decay(frequencies)
    enabled = enabled.groupby("dev_eui").aggregate(list)
    # only consider active devices
    active = get_active_devices(devices, records)
    devices = devices[active].join(enabled.rename("chmask"))
    print(devices)

    ut.set_channel_mask_configs(ns, devices["chmask"])


def device_freq_nrecv_ttest(freqs: pd.DataFrame, records: pd.DataFrame) -> pd.DataFrame:
    """statistical test on recv with truncated T Student distributon for low sample sizes"""
    df = records  # shallow copy

    def deduplicate_records(records: pd.DataFrame) -> pd.DataFrame:
        tx_id = ["_time", "log_id"]  # unique uplink transmission
        return records.drop_duplicates(tx_id)

    # deduplicate packets, sort by timestamp
    df = deduplicate_records(df).sort_values("_time")

    # this is for when we compute device-level metrics that need to be reindexed to every device frequency
    def reindex_to_device_freq(s: pd.Series) -> pd.Series:
        return s.reindex(freqs.index.get_level_values("dev_eui")).set_axis(freqs.index)

    # compute the number of active frequencies per device (i.e. our sample size)
    nfreq = freqs[freqs["enabled"]].groupby("dev_eui")["index"].count().rename("nfreq")
    nfreq = reindex_to_device_freq(nfreq)

    # count device received packets per frequency, reindex to all frequencies
    nrecv = df.groupby(["dev_eui", "frequency"])["f_cnt"].count().rename("nrecv")
    nrecv = nrecv.reindex(freqs.index)  # expand to unseen/disabled channel

    # fill Nan with 0 for active freqs so they are not ignored in the test
    # WARNING: this generates false positives if the device has been recently 
    # activated and no packets have been received yet on a certain frequency!
    nrecv[freqs["enabled"]] = nrecv[freqs["enabled"]].fillna(0)

    # compute empirical mean and standard deviation
    mean = nrecv.groupby("dev_eui").mean().rename("mean")
    mean = reindex_to_device_freq(mean)
    std = nrecv.groupby("dev_eui").std().rename("std")
    std = reindex_to_device_freq(std)

    # get device frame counter diff, manage disconnections and starting values
    fcnt_diff = df.set_index("dev_eui").groupby("dev_eui")["f_cnt"].diff()
    fcnt_diff = fcnt_diff.mask(lambda x: x <= 0, None).fillna(1)
    # sum-up to compute sent packets estimate
    nsent = fcnt_diff.groupby("dev_eui").sum().rename("nsent")
    nsent = reindex_to_device_freq(nsent)

    # configure truncation bounds
    lower = 0
    # max theoretical number of receptions per frequency
    upper = pd.Series(np.maximum(nrecv, nsent / nfreq)).groupby("dev_eui").max()
    upper = reindex_to_device_freq(upper)

    # warn: captures mean, std, nfreq
    def get_t_probability(value: pd.Series | int) -> pd.Series:
        # Nan can happen of dividing by 0 due to all same recv amounts
        t_value = (value - mean) / std * nfreq**0.5
        return pd.Series(sps.t.cdf(t_value, nfreq - 1), freqs.index)

    # compute probability values for observation, lower and upper bound
    p_obser = get_t_probability(nrecv)
    p_lower = get_t_probability(lower)
    p_upper = get_t_probability(upper)

    # compute truncated probability and evaluate outliers
    p_trunc = ((p_obser - p_lower) / (p_upper - p_lower)).rename("pvalue")
    outlier = (p_trunc < PVALUE_THRESHOLD).rename("outlier")

    # output relevant metrics
    return pd.concat([nfreq, nsent, nrecv, p_trunc, outlier], axis=1)


def get_active_devices(devices: pd.DataFrame, records: pd.DataFrame):
    active = records["dev_eui"].unique()
    return devices.index.isin(active)


def get_enabled_with_decay(frequencies: pd.DataFrame) -> pd.Series:
    global DECAYING

    # store current timestamp
    now = time.time()

    # manage unseen data: cast NaN to bool
    outliers = frequencies["enabled"] & frequencies["outlier"].astype(bool)

    # set non-outliers to enabled frequency indices
    enabled = frequencies.loc[~outliers, "index"]
    # restore decayed configurations
    if not DECAYING.empty:
        # drop obsolete decaying configs (e.g., due to session reset)
        DECAYING = DECAYING[DECAYING["index"].isin(frequencies["index"])]
        # drop configs not yet delivered that somehow got better
        DECAYING = DECAYING[~DECAYING["index"].isin(enabled)]
        # evaluate decay threshold
        decayed = DECAYING["timestamp"] + CONFIG_DECAY_THRESHOLD < now
        # re-add them to enabled set without timestamp
        enabled = pd.concat([enabled, DECAYING.loc[decayed, "index"]], axis=0)
        enabled = enabled.sort_values().astype(int)
        # remove decayed configs from global table
        DECAYING = DECAYING[~decayed]

    # set outliers to disabled frequency indices
    disabled = frequencies.loc[outliers, ["index"]]
    # filter out channels with an already running decay
    if not DECAYING.empty:
        disabled = disabled[~disabled.isin(DECAYING[["index"]])]
    # update decaying table with new disabled channels
    DECAYING = pd.concat([DECAYING, disabled.assign(timestamp=now)], axis=0)

    return enabled


def cleanup(ns):
    devices = ut.get_devices(ns)
    dev_euis = list(devices.index)
    ut.delete_channel_mask_configs(ns, dev_euis)


def set_lookback_horizon(seconds: int):
    global LOOKBACK_HORIZON
    LOOKBACK_HORIZON = seconds


def set_low_tstudent_pvalue_threshold(threshold: float):
    global PVALUE_THRESHOLD
    PVALUE_THRESHOLD = threshold


def set_config_decay_threshold(seconds: int):
    global CONFIG_DECAY_THRESHOLD
    CONFIG_DECAY_THRESHOLD = seconds
