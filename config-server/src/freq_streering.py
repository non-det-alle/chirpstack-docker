import time

import pandas as pd
import numpy as np
import scipy.stats as sps

from . import utilities as ut

LOOKBACK_HORIZON = 1 * 60 * 60  # seconds

PVALUE_THRESHOLD = 0.05

CONFIG_DECAY_THRESHOLD = 1 * 60 * 60  # seconds
CONFIG_RECOVER_THRESHOLD = 1 * 60 * 60  # seconds


# mutable global table
DECAYING = pd.Series()
RECOVERING = pd.Series()


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
    chmask = get_chmask_with_decay_and_recover(frequencies)
    devices = devices.join(chmask)
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


def get_chmask_with_decay_and_recover(freqs: pd.DataFrame) -> pd.Series:
    global DECAYING
    global RECOVERING

    # store current timestamp
    now = time.time()

    # pop expired decaying configs
    decayed = DECAYING[now > DECAYING + CONFIG_DECAY_THRESHOLD]
    DECAYING = DECAYING.drop(decayed.index)

    # pop expired recovering configs
    recovered = RECOVERING[now > RECOVERING + CONFIG_RECOVER_THRESHOLD]
    RECOVERING = RECOVERING.drop(recovered.index)

    # state machine:
    # enabled  -> enabled: ~outlier | recovering
    #          -> disabled: outlier & ~recovering -> decaying
    # disabled -> disabled: ~decayed
    #          -> enabled: decayed                -> recovering
    enabled = freqs["enabled"]
    outlier = freqs["outlier"]
    recovering = freqs.index.isin(RECOVERING.index)
    decayed = freqs.index.isin(decayed.index)

    # currently enabled
    etoe = freqs[enabled & (~outlier | recovering)]
    etod = freqs[enabled & outlier & ~recovering]
    # update decaying configs
    DECAYING = pd.concat([DECAYING, pd.Series(now, index=etod.index)])

    # currently disabled
    dtod = freqs[~enabled & ~decayed]  # unused
    dtoe = freqs[~enabled & decayed]
    # update recovering configs
    RECOVERING = pd.concat([RECOVERING, pd.Series(now, index=dtoe.index)])

    # output chmask configs
    indices = pd.concat([etoe, dtoe]).sort_index()["index"].astype(int)
    return indices.groupby("dev_eui").aggregate(list).rename("chmask")


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


def set_config_recover_threshold(seconds: int):
    global CONFIG_RECOVER_THRESHOLD
    CONFIG_RECOVER_THRESHOLD = seconds
