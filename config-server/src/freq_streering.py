import time

import pandas as pd

from . import utilities as ut

LOOKBACK_HORIZON = 1 * 60 * 60  # seconds

LOW_ZSCORE_THRESHOLD = -3

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
    # compute and join freq stats from records
    freq_stats = get_device_freq_stats(records)
    frequencies = frequencies.join(freq_stats)
    print(frequencies)

    # check that we have data for all frequencies
    ready = get_ready_devices(devices, frequencies)
    # no device seen or has data for all freqs yet
    if frequencies.empty or all(~ready):
        raise ut.ConfigServerError("Not enough data")

    # (optional) aggregate device traffic metrics
    packet_toa_metrics = ut.get_packet_toa_metrics(records)
    records = records.join(packet_toa_metrics)
    device_sfs = ut.get_device_sf(records)
    devices = devices.join(device_sfs)
    device_toa_metrics = ut.get_device_toa_metrics(records)
    devices = devices.join(device_toa_metrics)
    device_pdr_metrics = ut.get_device_pdr_metrics(records)
    devices = devices.join(device_pdr_metrics)

    # generate chmask configs
    enabled = get_enabled_with_decay(frequencies)
    enabled = enabled.groupby("dev_eui").aggregate(list)
    devices = devices[ready].join(enabled.rename("chmask"))
    print(devices)

    ut.set_channel_mask_configs(ns, devices["chmask"])


def get_device_freq_stats(records: pd.DataFrame) -> pd.DataFrame:
    df = records  # shallow copy

    def deduplicate_records(records: pd.DataFrame) -> pd.DataFrame:
        tx_id = ["_time", "log_id"]  # unique uplink transmission
        return records.drop_duplicates(tx_id)

    # deduplicate packets, sort by timestamp
    df = deduplicate_records(df).sort_values("_time")

    # count received packets per device frequency
    recv = df.groupby(["dev_eui", "frequency"])["f_cnt"].count()
    recv = recv.astype(float).rename("nrecv")

    # get device frame counter diff, manage disconnections and starting values
    diff = df.set_index("dev_eui")
    diff = diff.groupby("dev_eui")["f_cnt"].diff()
    diff = diff.mask(lambda x: x <= 0, None).fillna(1)
    # sum-up sent packets
    sent = diff.groupby("dev_eui").sum().rename("nsent")

    # compute the packet delivery ratio
    sent, recv = sent.align(recv)
    pdr = (recv / sent).rename("pdr")
    pdr = pd.concat([recv, sent, pdr], axis=1)

    # compute stats
    pdr = pdr.join(pdr["pdr"].groupby("dev_eui").aggregate(["mean", "std"]))
    pdr = pdr.join(((pdr["pdr"] - pdr["mean"]) / pdr["std"]).fillna(0).rename("zscore"))
    pdr = pdr.join((pdr["zscore"] <= LOW_ZSCORE_THRESHOLD).rename("outlier"))

    return pdr


def get_ready_devices(devices: pd.DataFrame, frequencies: pd.DataFrame) -> pd.Series:
    df = frequencies  # shallow copy
    df = df["nrecv"].groupby("dev_eui").apply(lambda g: (g > 0).all()).astype(bool)
    df = df.reindex(devices.index).rename("ready")
    return df


def get_enabled_with_decay(frequencies: pd.DataFrame) -> pd.Series:
    global DECAYING

    # store current timestamp
    now = time.time()

    # manage unseen data: cast NaN to bool
    outliers = frequencies["outlier"].astype(bool)

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


def set_config_decay_threshold(seconds: int):
    global CONFIG_DECAY_THRESHOLD
    CONFIG_DECAY_THRESHOLD = seconds
