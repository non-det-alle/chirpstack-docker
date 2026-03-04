import signal

import numpy as np
import scipy.special as sp
import pandas as pd

from .config import config
from .chirpstack_client import ChirpStackClient as NS
from .influxdb_client_wrapper import InfluxDBClientWrapper as DB
from .chirpstack_client import DeviceConfigStore, to_dict, NotFoundError


class ConfigServerError(Exception):
    name = "ConfigServerError"
    def __init__(self, cause):
        self.args = (f"{self.name}: {cause}",)
        super().__init__(*self.args)


class NetworkServerError(ConfigServerError):
    name = "NetworkServerError"


class DataBaseError(ConfigServerError):
    name = "DataBaseError"


def NetworkServer():
    return NS(config.CHIRPSTACK_ENDPOINT, config.CHIRPSTACK_TOKEN)


def DataBase():
    return DB(
        config.INFLUXDB_URL,
        config.INFLUXDB_TOKEN,
        config.INFLUXDB_ORG,
        config.INFLUXDB_BUCKET,
    )


def on_sigterm(f):
    def handler(*_):
        f()
        # restore and propagate
        signal.signal(signal.SIGTERM, default)
        signal.raise_signal(signal.SIGTERM)

    default = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, handler)
    return f


def capacity_from_pdr(pdr):
    gt = -np.log(0.98)
    gamma = np.pow(10.0, 1.0 / 10.0)
    a = (gamma + 1.0) / (1.0 + gamma * (1.0 - np.exp(-gt + 1.0 / gamma)))
    return -0.5 * (a + sp.lambertw(-(a / np.exp(a))).real * np.exp(gt) * np.array(pdr))


def get_devices(ns: NS) -> pd.DataFrame:
    try:
        tenant_id = ns.get_tenant_id(config.CHIRPSTACK_TENANT)
        application_id = ns.get_application_ids(tenant_id)[0]
        device_list = ns.list_devices(application_id)
    except Exception as e:
        raise NetworkServerError(e) from e
    device_list = pd.DataFrame(device_list)
    device_list = device_list.set_index("dev_eui").sort_index()
    return device_list


def get_freq_indices(ns: NS, dev_euis: list[str]) -> pd.DataFrame:
    def get_channels(dev_eui):
        try:
            params = to_dict(ns.get_device_current_params(dev_eui))
        except NotFoundError:
            return pd.DataFrame()
        except Exception as e:
            raise NetworkServerError(e) from e
        channels = pd.DataFrame(params["channels"]).T["frequency"].reset_index()
        channels = channels.assign(dev_eui=dev_eui, index=channels["index"].astype(int))
        channels = channels.set_index(["dev_eui", "frequency"]).sort_values("index")
        return channels

    return pd.concat((get_channels(d) for d in dev_euis), axis=0)


def set_channel_mask_configs(ns: NS, configs: pd.Series):
    for dev_eui, chmask in configs.items():
        config_store = DeviceConfigStore(enabled_uplink_channel_indices=chmask)
        try:
            ns.set_device_config(str(dev_eui), config_store)
        except Exception as e:
            raise NetworkServerError(e) from e


def delete_channel_mask_configs(ns: NS, dev_euis: list[str]):
    for d in dev_euis:
        try:
            ns.delete_device_config(d)
        except Exception as e:
            raise NetworkServerError(e) from e


def get_traffic_records(db: DB, dev_euis: list[str], since_s: int) -> pd.DataFrame:
    try:
        records = db.get_traffic_records(f"-{since_s}s", dev_eui=dev_euis)
    except Exception as e:
        raise DataBaseError(e) from e
    return records


def clean_traffic_records(records: pd.DataFrame) -> pd.DataFrame:
    df = records  # shallow copy

    def rename_columns(records: pd.DataFrame) -> pd.DataFrame:
        columns = {
            # get_phy_payload_len
            "phy_payload.payload.f_port": "f_port",
            "phy_payload.payload.fhdr.f_ctrl.f_opts_len": "f_opts_len",
            "phy_payload.payload.frm_payload": "frm_payload",
            # get_toa
            "tx_info.modulation.lora.spreading_factor": "sf",
            "tx_info.modulation.lora.bandwidth": "bw",
            "tx_info.modulation.lora.code_rate": "cr",
            "rx_info.crc_status": "crc_status",
            # get_device_best_gateway
            "rx_info.gateway_id": "gateway_id",
            "rx_info.snr": "snr",
            "rx_info.rssi": "rssi",
            # get_device_pdr
            "phy_payload.payload.fhdr.f_cnt": "f_cnt",
            # other
            "tx_info.frequency": "frequency",
        }
        return records.rename(columns=columns)

    df = rename_columns(df)

    def drop_null_values(records: pd.DataFrame) -> pd.DataFrame:
        required_notna_fields = ["sf", "bw", "cr", "crc_status", "f_cnt"]
        # remove rows with null values in fields needed for ToA computation
        return records.dropna(subset=required_notna_fields)

    df = drop_null_values(df)

    def format_fields(records: pd.DataFrame) -> pd.DataFrame:
        df = records  # shallow copy
        # get_phy_payload_len
        df["f_opts_len"] = df["f_opts_len"].astype(int)
        df["frm_payload_len"] = df["frm_payload"].str.len().div(2).astype(int)
        # get_toa
        df["sf"] = df["sf"].astype(int)
        df["bw"] = df["bw"].astype(int)
        df["cr"] = df["cr"].str.removeprefix("CR_4_").astype(int).sub(4)
        df["crc"] = df["crc_status"].ne("NO_CRC")
        # get_device_pdr
        df["f_cnt"] = df["f_cnt"].astype(int)
        # other
        df["frequency"] = df["frequency"].astype(int)
        return df

    df = format_fields(df)

    return df


def get_packet_toa_metrics(records: pd.DataFrame) -> pd.DataFrame:
    # compute phy payload length
    phy_payload_len = get_phy_payload_len(records)
    # compute record time on ai
    time_on_air = get_time_on_air(records.join(phy_payload_len))
    return pd.concat([phy_payload_len, time_on_air], axis=1)


def drop_devices_with_non_unique_sf(records: pd.DataFrame) -> pd.DataFrame:
    # remove records of devices who changed SF
    return records.groupby(["dev_eui"]).filter(lambda x: len(x["sf"].unique()) == 1)


def get_phy_payload_len(records: pd.DataFrame) -> pd.Series:
    df = records  # shallow copy

    def phy_payload_len(f_port, f_opts_len, frm_payload_len):
        f_port_present = f_port.notna()
        # Fixed 12B for MHDR(1) + DevAddr(4) + FCtrl(1) + FCnt(2) + MIC(4)
        return 12 + f_port_present + f_opts_len + frm_payload_len

    df = phy_payload_len(df["f_port"], df["f_opts_len"], df["frm_payload_len"])
    return df.rename("phy_payload_len")


def get_time_on_air(records: pd.DataFrame) -> pd.Series:
    df = records  # shallow copy

    def toa(pl, sf, bw, cr, crc, n_preamble=8, de=1, ih=0):
        # see, SX1272 datasheet
        t_sym = 2**sf / bw
        t_premble = (n_preamble + 4.25) * t_sym
        num = 8 * pl - 4 * sf + 28 + 16 * crc - 20 * ih
        den = 4 * (sf - 2 * de)
        n_payload = 8 + np.fmax(np.ceil(num / den) * (cr + 4), 0)
        t_payload = n_payload * t_sym
        return t_premble + t_payload

    df = toa(df["phy_payload_len"], df["sf"], df["bw"], df["cr"], df["crc"])
    return df.rename("time_on_air")


def get_device_sf(records: pd.DataFrame) -> pd.Series:
    df = records  # shallow copy
    # deduplicate sf usage records
    df = df.drop_duplicates(["dev_eui", "sf"])
    # tranform to a per device list
    df = df.groupby("dev_eui")["sf"].apply(list)
    return df


def get_device_best_gateway_snr(records: pd.DataFrame) -> pd.DataFrame:
    df = records  # shallow copy
    # max historical snr for each dev & gw pairing
    df = df.groupby(["dev_eui", "gateway_id"])["snr"].max()
    # max resulting snr among gateways for each dev
    df = df[df.groupby("dev_eui").idxmax()]
    # return snr and best gateway
    df = df.reset_index("gateway_id")
    return df


def deduplicate_records(records: pd.DataFrame) -> pd.DataFrame:
    tx_id = ["_time", "log_id"]  # unique uplink transmission
    return records.drop_duplicates(tx_id)


def get_device_toa_metrics(records: pd.DataFrame) -> pd.DataFrame:
    df = records  # shallow copy

    # deduplicate packets, sort by timestamp
    df = deduplicate_records(df).sort_values("_time")
    # index and group by device
    df = df.set_index("dev_eui").groupby("dev_eui")

    def get_device_phy_bytes(records) -> pd.Series:
        # total phy payload bytes
        return records["phy_payload_len"].sum().rename("phy_bytes")

    phy_bytes = get_device_phy_bytes(df)

    def get_device_time_on_air(records) -> pd.Series:
        # total time on air (s)
        return records["time_on_air"].sum()

    time_on_air = get_device_time_on_air(df)

    return pd.concat([phy_bytes, time_on_air], axis=1)


def get_device_pdr_metrics(records: pd.DataFrame) -> pd.DataFrame:
    df = records  # shallow copy

    # deduplicate packets, sort by timestamp
    df = deduplicate_records(df).sort_values("_time")
    # index and group by device
    df = df.set_index("dev_eui").groupby("dev_eui")

    def get_device_pdr(records) -> pd.DataFrame:
        # count received packets
        recv = records["f_cnt"].count().astype(float).rename("nrecv")
        # get frame counter diff, manage disconnections and starting values
        diff = records["f_cnt"].diff().mask(lambda x: x <= 0, None).fillna(1)
        # sum-up sent packets
        sent = diff.groupby("dev_eui").sum().rename("nsent")
        # compute the packet delivery ratio
        pdr = (recv / sent).rename("pdr")
        # join the three dev_eui-indexed series
        return pd.concat([recv, sent, pdr], axis=1)

    return get_device_pdr(df)
