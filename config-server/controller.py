from src.utilities import *
from src.globecom22 import globecom22


FREQUENCIES = (868100000, 868300000, 868500000)
# , 867100000, 867300000, 867500000, 867700000, 867900000)
DATARATES = (0, 1, 2, 3, 4, 5)

CLUSTERS = pd.DataFrame({
    "name"       : ("ultra_high_reliability", "high_reliability", "best_effort"),
    "pdr"        : (0.97                    , 0.90              , 0.70         ),
    "dev_percent": (0.1                     , 0.3               , 0.6          ),
    "id"         : (0                       , 1                 , 2            ),
}).set_index("name", verify_integrity=True)
CLUSTERS = CLUSTERS.assign(max_ot=capacity_from_pdr(CLUSTERS["pdr"])) # on a SF on a freq.

print(CLUSTERS, "\n")

EPOCH = 1 * 60 * 60  # seconds


def get_updated_tags_with_cluster(ns: ChirpStackClient, devices: pd.DataFrame):
    tags = devices["tags"].apply(pd.Series)
    if not tags.empty and "cluster" not in tags:
        cluster = ["high_reliability"] + ["best_effort"] * (len(tags) - 1)
        tags  = tags.assign(cluster=cluster)
        _ = [ns.set_device_tags(str(d), dict(t)) for d, t in tags.iterrows()]
    tags = tags.assign(bps=tags["bps"].astype(float))
    return tags


with DataBase() as db, NetworkServer() as ns:

    ### TRAFFIC RECORDS
    records = get_traffic_records(db, EPOCH)
    print("len after get_traffic_records", len(records))
    records = clean_traffic_records(records)
    print("len after clean_traffic_records", len(records))
    # compute phy payload length
    phy_payload_len = get_phy_payload_len(records)
    records = records.assign(phy_payload_len=phy_payload_len)
    # compute record time on air
    time_on_air = get_time_on_air(records)
    records = records.assign(time_on_air=time_on_air)
    print(records)

    ### DEVICE METRICS
    devices = get_devices(ns)
    devices = get_updated_tags_with_cluster(ns, devices)
    # join SF data to devices
    spreading_factors = get_device_sf(records)
    devices = devices.join(spreading_factors)
    # get best gateway snr
    best_gateway_snr = get_device_best_gateway_snr(records)
    devices = devices.join(best_gateway_snr)
    # get device traffic metrics
    device_metrics = get_device_metrics(records)
    devices = devices.join(device_metrics)
    # compute measured bitrate and scale estimate via pdr
    bitrate = devices["phy_bytes"] * 8 / EPOCH  # bit/s
    bitrate = bitrate / devices["pdr"]
    devices = devices.assign(bitrate=bitrate)
    # compute measured offered traffic and scale estimate via pdr
    offered_traffic = devices["time_on_air"] / EPOCH  # Erlang
    offered_traffic = offered_traffic / devices["pdr"]
    devices = devices.assign(offered_traffic=offered_traffic)

    # in theory only the snr is needed for channel allocation
    # bitrate may be substituted by declared throughput as a tag

    ### GLOBECOM CHMASK ASSIGN
    devices = globecom22(devices, CLUSTERS["max_ot"], len(FREQUENCIES))
    print(devices)

    # set_channel_mask_configs(ns, devices["chmask"])

    # input("\nPress enter to clean-up configs and terminate program...")
    # delete_channel_mask_configs(ns, list(devices.index))
