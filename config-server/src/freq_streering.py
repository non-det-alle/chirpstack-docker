import time

import pandas as pd

from .utilities import *
from .chirpstack_client import to_dict

LOOKBACK_ORIZON = 1 * 60 * 60  # seconds

LOW_ZSCORE_THRESHOLD = -3

CONFIG_DECAY_THRESHOLD = 1 * 60 * 60  # seconds


# mutable global table
DECAYING = pd.DataFrame()


def run(ns: ChirpStackClient, db: InfluxDBClientWrapper):
    # load records
    records = get_traffic_records(db, LOOKBACK_ORIZON)
    records = clean_traffic_records(records)
    packet_toa_metrics = get_packet_toa_metrics(records)
    records = records.join(packet_toa_metrics)

    # load devices
    devices = get_devices(ns)[["name"]]
    # get device traffic metrics
    device_toa_metrics = get_device_toa_metrics(records)
    devices = devices.join(device_toa_metrics)
    device_pdr_metrics = get_device_pdr_metrics(records)
    devices = devices.join(device_pdr_metrics)

    # load frequencies from server configs
    frequencies = get_freq_indices(ns, list(devices.index))
    if frequencies.empty:
        print("No device seen (yet), postponing.")
        return
    # compute and join freq stats from records
    freq_stats = get_device_freq_stats(records)
    frequencies = frequencies.join(freq_stats)
    print(frequencies)

    # generate chmask configs
    enabled = get_enabled_with_decay(frequencies)
    enabled = enabled.groupby("dev_eui").aggregate(list)
    devices = devices.join(enabled.rename("chmask"))
    print(devices)

    set_channel_mask_configs(ns, devices["chmask"])


def get_freq_indices(ns: ChirpStackClient, dev_euis: list[str]) -> pd.DataFrame:
    def get_channels(dev_eui):
        try:
            params = ns.get_device_current_params(dev_eui)
            channels = pd.DataFrame(to_dict(params)["channels"]).T["frequency"].reset_index()
            channels = channels.assign(dev_eui=dev_eui, index=channels["index"].astype(int))
            channels = channels.set_index(["dev_eui", "frequency"])
        except ValueError:
            return pd.DataFrame()
        return channels

    return pd.concat((get_channels(d) for d in dev_euis), axis=0)


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


def get_enabled_with_decay(frequencies: pd.DataFrame) -> pd.Series:
    global DECAYING

    # store current timestamp
    now = time.time()

    # set non-outliers to enabled frequency indices
    enabled = frequencies.loc[~frequencies["outlier"], "index"]
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
    disabled = frequencies.loc[frequencies["outlier"], ["index"]]
    # filter out channels with an already running decay
    if not DECAYING.empty:
        disabled = disabled[~disabled.isin(DECAYING[["index"]])]
    # update decaying table with new disabled channels
    DECAYING = pd.concat([DECAYING, disabled.assign(timestamp=now)], axis=0)

    return enabled


@on_sigterm
def cleanup(ns):
    devices = get_devices(ns)
    dev_euis = list(devices.index)
    delete_channel_mask_configs(ns, dev_euis)
