from utilities import *
from globecom22 import globecom22

print(CLUSTERS, "\n")

EPOCH = 1 * 60 * 60  # seconds


### TRAFFIC RECORDS
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


### DEVICE METRICS
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


### GLOBECOM CHMASK ASSIGN
devices = globecom22(devices)
print(devices)

set_channel_mask_configs(devices["chmask"])

input("\nPress enter to clean-up configs and terminate program...")
delete_channel_mask_configs(list(devices.index))