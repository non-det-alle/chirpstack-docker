import time

import pandas as pd
import scipy.stats as sps

from . import utilities as ut

LOOKBACK_HORIZON = 1 * 60 * 60  # seconds

LOW_ZSCORE_THRESHOLD = -3
LOW_TSTUDENT_QUANTILE_THRESHOLD = 0.1

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
    if records.empty:
        raise ut.ConfigServerError("Not enough data")

    # load frequencies from server device session
    frequencies = ut.get_freq_indices(ns, dev_euis)
    # compute and join freq stats from records
    freq_stats = get_device_freq_stats(frequencies, records)
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


def get_device_freq_stats(freqs: pd.DataFrame, records: pd.DataFrame) -> pd.DataFrame:
    df = records  # shallow copy

    def deduplicate_records(records: pd.DataFrame) -> pd.DataFrame:
        tx_id = ["_time", "log_id"]  # unique uplink transmission
        return records.drop_duplicates(tx_id)

    # deduplicate packets, sort by timestamp
    df = deduplicate_records(df).sort_values("_time")

    # count device used frequencies
    recv = df.groupby(["dev_eui", "frequency"])["f_cnt"].count().rename("nrecv")
    recv = recv.reindex(freqs.index).fillna(0)

    # get device frame counter diff, manage disconnections and starting values
    diff = df.set_index("dev_eui").groupby("dev_eui")["f_cnt"].diff()
    diff = diff.mask(lambda x: x <= 0, None).fillna(1)
    # sum-up sent packets
    sent = diff.groupby("dev_eui").sum().rename("nsent")
    sent = sent.reindex(freqs.index.get_level_values("dev_eui")).set_axis(freqs.index)

    # compute the number of active frequencies per device
    nfreq = freqs[freqs["enabled"]].groupby("dev_eui")["index"].count().rename("nfreq")
    nfreq = nfreq.reindex(freqs.index.get_level_values("dev_eui")).set_axis(freqs.index)

    # compute the packet reception share
    share = (recv.astype(float) / sent).rename("share")

    # join metrics
    df = pd.concat([nfreq, recv, sent, share], axis=1)

    # compute stats
    df = df.join(recv.groupby("dev_eui").aggregate(["mean", "std"]))
    # Nan can happen of dividing by 0 due to all same recv amounts
    df = df.join(((recv - df["mean"]) / df["std"]).fillna(0).rename("zscore"))
    df = df.join((df["zscore"] * (nfreq**0.5)).fillna(0).rename("tscore"))
    # df = df.join((df["zscore"] <= LOW_ZSCORE_THRESHOLD).rename("ztest"))
    low_student_threshold = sps.t.ppf(LOW_TSTUDENT_QUANTILE_THRESHOLD, df["nfreq"] - 1)
    df = df.join((df["tscore"] <= low_student_threshold).rename("ttest"))

    return df


def get_active_devices(devices: pd.DataFrame, records: pd.DataFrame):
    active = records["dev_eui"].unique()
    return devices.index.isin(active)


def get_enabled_with_decay(frequencies: pd.DataFrame) -> pd.Series:
    global DECAYING

    # store current timestamp
    now = time.time()

    # manage unseen data: cast NaN to bool
    outliers = frequencies["ttest"].astype(bool)

    # set non-outliers to enabled frequency indices
    enabled = frequencies.loc[~outliers, "index"]
    # restore decayed configurations
    if not DECAYING.empty:
        # drop obsolete decaying configs (e.g., due to session reset)
        DECAYING = DECAYING[DECAYING["index"].isin(frequencies["index"])]
        # drop configs not yet delivered that somehow got better
        DECAYING = DECAYING[~DECAYING["index"].isin(enabled)]
        # evaluate decay threshold
        decayed = DECAYING["timestamp"] + CONFIG_DECAY_THRESHOLD > now
        # re-add them to enabled set without timestamp
        enabled = pd.concat([enabled, DECAYING.loc[decayed, "index"]], axis=0)
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


def set_low_zscore_threshold(threshold: float):
    global LOW_ZSCORE_THRESHOLD
    LOW_ZSCORE_THRESHOLD = threshold


def set_low_tstudent_quantile_threshold(threshold: float):
    global LOW_TSTUDENT_QUANTILE_THRESHOLD
    LOW_TSTUDENT_QUANTILE_THRESHOLD = threshold


def set_config_decay_threshold(seconds: int):
    global CONFIG_DECAY_THRESHOLD
    CONFIG_DECAY_THRESHOLD = seconds
