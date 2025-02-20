#!/usr/bin/env python3
"""
Scheduled Discovery Script for Infoblox

This script updates the scheduled discovery task using network objects that have the
'Network_Discovery' extensible attribute set to True. It filters networks by the
configured network view and, if no valid networks are found, falls back to a default
network (after retrieving its proper _ref via Infoblox WAPI).

All events are logged to 'discovery.log' with each line prefixed by
"SCHEDULED_DISCOVERY_SCRIPT".
"""

import requests
import yaml
import json
import logging
import sys
import os
import ipaddress
from urllib.parse import urlparse
from rich import print

# -----------------------------------------------------------------------------
# SCRIPT TYPE FOR LOGGING
# -----------------------------------------------------------------------------
SCRIPT_TYPE = "SCHEDULED_DISCOVERY_SCRIPT"

# -----------------------------------------------------------------------------
# LOGGING SETUP
# -----------------------------------------------------------------------------
logging.basicConfig(
    filename='discovery.log',
    level=logging.INFO,  # Change to DEBUG for more verbose output
    format=f'%(asctime)s {SCRIPT_TYPE} %(levelname)s %(message)s'
)

# -----------------------------------------------------------------------------
# HELPER: VALIDATE CONFIGURATION
# -----------------------------------------------------------------------------
def validate_config(cfg):
    """
    Validate required configuration fields.

    Required:
      - INFOBLOX_API_URL: Must be a valid URL.
      - INFOBLOX_API_USERNAME and INFOBLOX_API_PASSWORD: Must be non-empty.
      - SCHEDULED_DISCOVERY_NETWORK_VIEW: Must be non-empty.
      - SCHEDULED_DISCOVERY_DEFAULT_NETWORK (optional): If present, must be a valid CIDR.
    Returns True if configuration is valid, False otherwise.
    """
    valid = True

    api_url = cfg.get("INFOBLOX_API_URL", "")
    if not api_url:
        logging.error("Config error: INFOBLOX_API_URL is empty or missing.")
        valid = False
    else:
        parsed = urlparse(api_url)
        if not (parsed.scheme and parsed.netloc):
            logging.error("Config error: INFOBLOX_API_URL '%s' is not a valid URL.", api_url)
            valid = False

    username = cfg.get("INFOBLOX_API_USERNAME", "")
    password = cfg.get("INFOBLOX_API_PASSWORD", "")
    if not username:
        logging.error("Config error: INFOBLOX_API_USERNAME is empty or missing.")
        valid = False
    if not password:
        logging.error("Config error: INFOBLOX_API_PASSWORD is empty or missing.")
        valid = False

    view = cfg.get("SCHEDULED_DISCOVERY_NETWORK_VIEW", "")
    if not view:
        logging.error("Config error: SCHEDULED_DISCOVERY_NETWORK_VIEW is empty or missing.")
        valid = False

    fallback = cfg.get("SCHEDULED_DISCOVERY_DEFAULT_NETWORK", "")
    if fallback:
        try:
            ipaddress.ip_network(fallback, strict=False)
        except ValueError:
            logging.error("Config error: SCHEDULED_DISCOVERY_DEFAULT_NETWORK '%s' is not a valid IP network.", fallback)
            valid = False

    return valid

# -----------------------------------------------------------------------------
# LOAD CONFIGURATION FROM YAML (FROM SCRIPT DIRECTORY)
# -----------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.yaml")

try:
    with open(CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f)
except Exception as e:
    logging.error("Could not read the config file '%s'. Error: %s", CONFIG_FILE, e, exc_info=True)
    sys.exit(1)

if not validate_config(config):
    logging.error("Configuration validation failed. Exiting.")
    print("Configuration validation failed. Check discovery.log for details.")
    sys.exit(1)

INFOBLOX_API_URL = config["INFOBLOX_API_URL"]
USERNAME         = config["INFOBLOX_API_USERNAME"]
PASSWORD         = config["INFOBLOX_API_PASSWORD"]
SCHEDULED_DISCOVERY_NETWORK_VIEW = config.get("SCHEDULED_DISCOVERY_NETWORK_VIEW", "default")
SCHEDULED_DISCOVERY_DEFAULT_NETWORK = config.get("SCHEDULED_DISCOVERY_DEFAULT_NETWORK", "")

# -----------------------------------------------------------------------------
# GLOBAL SETTINGS
# -----------------------------------------------------------------------------
WAPI_VERSION = "v2.12"
VERIFY_SSL   = False
if not VERIFY_SSL:
    requests.packages.urllib3.disable_warnings()
BASE_URL = f"{INFOBLOX_API_URL}/wapi/{WAPI_VERSION}"

# -----------------------------------------------------------------------------
# FUNCTIONS
# -----------------------------------------------------------------------------

def get_scheduled_discovery_ref():
    """
    Retrieve the scheduled discovery task _ref from Infoblox.
    """
    url = f"{BASE_URL}/discoverytask?_return_as_object=1"
    try:
        r = requests.get(url, auth=(USERNAME, PASSWORD), verify=VERIFY_SSL)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error retrieving discovery tasks: %s", e, exc_info=True)
        return None
    data = r.json()
    for task in data.get("result", []):
        if task.get("discovery_task_oid") == "scheduled":
            logging.info("Found scheduled discovery task ref: %s", task["_ref"])
            return task["_ref"]
    logging.warning("No scheduled discovery task found.")
    return None

def get_discovery_enabled_networks():
    """
    Retrieve all network objects with the 'Network_Discovery' extensible attribute set to True.
    """
    url = f"{BASE_URL}/network?_return_fields=network,extattrs&_return_as_object=1&_max_results=1000000"
    try:
        resp = requests.get(url, auth=(USERNAME, PASSWORD), verify=VERIFY_SSL)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error retrieving network objects: %s", e, exc_info=True)
        return []
    data = resp.json()
    all_networks = data.get("result", [])
    found = []
    for net_obj in all_networks:
        extattrs = net_obj.get("extattrs", {})
        if extattrs.get("Network_Discovery", {}).get("value") == "True":
            found.append(net_obj["_ref"])
    logging.info("Found %d networks with Network_Discovery=True", len(found))
    return found

def filter_by_view(network_refs, desired_view):
    """
    Filter a list of network references to include only those ending with '/<desired_view>'.
    """
    suffix = f"/{desired_view}"
    return [ref for ref in network_refs if ref.endswith(suffix)]

def get_network_ref(network_cidr, network_view):
    """
    Query Infoblox to get the network object _ref for a given network CIDR and view.
    """
    url = f"{BASE_URL}/network?network={network_cidr}&network_view={network_view}&_return_as_object=1"
    try:
        r = requests.get(url, auth=(USERNAME, PASSWORD), verify=VERIFY_SSL)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error retrieving network ref for %s: %s", network_cidr, e, exc_info=True)
        return None
    data = r.json()
    result = data.get("result", [])
    if result:
        ref = result[0].get("_ref")
        logging.info("Found network ref for %s in view '%s': %s", network_cidr, network_view, ref)
        return ref
    else:
        logging.error("No network object found for network: %s in view: %s", network_cidr, network_view)
        return None

def update_scheduled_discovery_task(task_ref, network_refs, mode="ICMP", ping_retries=5, ping_timeout=1500):
    """
    Overwrite the scheduled discovery task with the provided network references.
    Returns True on success, False on failure.
    """
    url = f"{BASE_URL}/{task_ref}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "mode": mode,
        "network_view": SCHEDULED_DISCOVERY_NETWORK_VIEW,
        "networks": network_refs,
        "ping_retries": ping_retries,
        "ping_timeout": ping_timeout
    }
    logging.info("Overwriting scheduled discovery '%s' with %d networks in view '%s'.",
                 task_ref, len(network_refs), SCHEDULED_DISCOVERY_NETWORK_VIEW)
    try:
        resp = requests.put(url, auth=(USERNAME, PASSWORD), headers=headers, data=json.dumps(payload), verify=VERIFY_SSL)
        resp.raise_for_status()
        logging.info("Scheduled discovery updated successfully. HTTP code: %d", resp.status_code)
        return True
    except requests.exceptions.RequestException as e:
        logging.error("Error updating scheduled discovery with new networks: %s", e, exc_info=True)
        return False

def get_discovery_task_status(task_ref):
    """
    Retrieve the status and state of the given discovery task.
    """
    url = f"{BASE_URL}/discoverytask?_return_as_object=1&_return_fields%2B=status,state"
    try:
        r = requests.get(url, auth=(USERNAME, PASSWORD), verify=VERIFY_SSL)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error retrieving discovery task status: %s", e, exc_info=True)
        return None, None
    data = r.json()
    for task in data.get("result", []):
        if task.get("_ref") == task_ref:
            return task.get("state"), task.get("status")
    return None, None

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    """
    Main function to update the scheduled discovery task.
    """
    scheduled_ref = get_scheduled_discovery_ref()
    if not scheduled_ref:
        print("Could not find 'scheduled' discovery reference. Check discovery.log for details.")
        return

    # 1) Retrieve all networks with Network_Discovery=True
    discovered = get_discovery_enabled_networks()
    if discovered:
        # Filter discovered networks by the configured network view
        filtered = filter_by_view(discovered, SCHEDULED_DISCOVERY_NETWORK_VIEW)
        if filtered:
            networks = filtered
            logging.info("After filtering by view '%s', %d networks remain out of %d discovered.",
                         SCHEDULED_DISCOVERY_NETWORK_VIEW, len(filtered), len(discovered))
        else:
            logging.info("Discovered %d networks, but none match view '%s'. Will fallback if configured.",
                         len(discovered), SCHEDULED_DISCOVERY_NETWORK_VIEW)
            networks = []
    else:
        logging.info("No networks found with Network_Discovery=True.")
        networks = []

    # 2) If no valid networks found, fallback to the default network (if specified)
    if not networks:
        if SCHEDULED_DISCOVERY_DEFAULT_NETWORK:
            fallback_ref = get_network_ref(SCHEDULED_DISCOVERY_DEFAULT_NETWORK, SCHEDULED_DISCOVERY_NETWORK_VIEW)
            if fallback_ref:
                networks = [fallback_ref]
                logging.info("Using fallback network ref '%s' instead.", fallback_ref)
            else:
                logging.error("Fallback network '%s' not found in view '%s'.",
                              SCHEDULED_DISCOVERY_DEFAULT_NETWORK, SCHEDULED_DISCOVERY_NETWORK_VIEW)
                print("Fallback network not found; update skipped. Check discovery.log for details.")
                return
        else:
            logging.info("No networks found and no fallback network specified. Nothing to update.")
            print("No networks found; no fallback specified; update skipped.")
            return

    # 3) Update the scheduled discovery task with the selected networks
    success = update_scheduled_discovery_task(scheduled_ref, networks)
    if not success:
        print("An error occurred while updating the scheduled discovery. Please check discovery.log.")
        return

    # 4) Optionally, check final state
    state, status_msg = get_discovery_task_status(scheduled_ref)
    if state:
        logging.info("Scheduled Discovery State: %s", state)
        print(f"Scheduled Discovery State: {state}")
    else:
        logging.warning("Could not retrieve state/status for the scheduled task.")
        print("Could not retrieve scheduled discovery status. Check discovery.log for details.")

if __name__ == "__main__":
    try:
        main()
        print("Script finished successfully.")
    except Exception as ex:
        logging.error("Unhandled exception in main(): %s", ex, exc_info=True)
        sys.exit(1)
