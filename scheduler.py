#!/usr/bin/env python3
import requests
import yaml
import json
import logging
import sys

# -----------------------------------------------------------------------------
# LOGGING SETUP
# -----------------------------------------------------------------------------
# Configure logging to write to a file named 'discovery.log' with timestamp, level, and message.
logging.basicConfig(
    filename='discovery.log',
    level=logging.INFO,  # or DEBUG if you want more verbosity
    format='%(asctime)s %(levelname)s %(message)s'
)

# -----------------------------------------------------------------------------
# LOAD CONFIG FROM YAML
# -----------------------------------------------------------------------------
CONFIG_FILE = "config.yaml"
try:
    with open(CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f)
except Exception as e:
    logging.error("Could not read the config file '%s'. Error: %s", CONFIG_FILE, e, exc_info=True)
    sys.exit(1)

INFOBLOX_API_URL = config.get("INFOBLOX_API_URL", "")
USERNAME         = config.get("INFOBLOX_API_USERNAME", "")
PASSWORD         = config.get("INFOBLOX_API_PASSWORD", "")

if not INFOBLOX_API_URL or not USERNAME or not PASSWORD:
    logging.error("Missing required Infoblox configuration in %s", CONFIG_FILE)
    sys.exit(1)

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
    Find the Infoblox 'scheduled' discovery task reference automatically.
    Returns the _ref or None if not found.
    """
    url = f"{BASE_URL}/discoverytask?_return_as_object=1"

    try:
        resp = requests.get(url, auth=(USERNAME, PASSWORD), verify=VERIFY_SSL)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error retrieving discovery tasks: %s", e, exc_info=True)
        return None

    data = resp.json()
    tasks = data.get("result", [])
    for task in tasks:
        if task.get("discovery_task_oid") == "scheduled":
            logging.info("Found scheduled discovery task ref: %s", task["_ref"])
            return task["_ref"]
    logging.warning("No scheduled discovery task found.")
    return None

def get_discovery_enabled_networks():
    """
    Returns a list of network references that have Network_Discovery == 'True'.
    """
    url = f"{BASE_URL}/network?_return_fields=network,extattrs&_return_as_object=1&_max_results=1000000"

    try:
        resp = requests.get(url, auth=(USERNAME, PASSWORD), verify=VERIFY_SSL)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error retrieving network objects: %s", e, exc_info=True)
        return []

    data = resp.json()
    networks = data.get("result", [])

    results = []
    for net_obj in networks:
        extattrs = net_obj.get("extattrs", {})
        if extattrs.get("Network_Discovery", {}).get("value") == "True":
            results.append(net_obj["_ref"])

    logging.info("Found %d networks with Network_Discovery=True", len(results))
    return results

def update_scheduled_discovery_task(task_ref, network_refs,
                                    mode="ICMP", ping_retries=5, ping_timeout=1500):
    url = f"{BASE_URL}/{task_ref}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "mode": mode,
        "network_view": "GLOBAL",
        "networks": network_refs,
        "ping_retries": ping_retries,
        "ping_timeout": ping_timeout
    }    
    
    logging.info("Overwriting scheduled discovery '%s' with %d networks.", task_ref, len(network_refs))
    try:
        resp = requests.put(
            url,
            auth=(USERNAME, PASSWORD),
            headers=headers,
            data=json.dumps(payload),
            verify=VERIFY_SSL
        )
        resp.raise_for_status()
        logging.info("Scheduled discovery updated successfully. HTTP code: %d", resp.status_code)
        
    except requests.exceptions.RequestException as e:
        logging.error("Error updating scheduled discovery with new networks: %s", e, exc_info=True)
        
        return

def start_scheduled_discovery_task(task_ref):
    """
    Start the scheduled discovery.
    """
    url = f"{BASE_URL}/{task_ref}?_function=network_discovery_control"
    headers = {"Content-Type": "application/json"}
    payload = {"action": "START"}

    logging.info("Starting scheduled discovery: %s", task_ref)
    try:
        resp = requests.post(
            url,
            auth=(USERNAME, PASSWORD),
            headers=headers,
            data=json.dumps(payload),
            verify=VERIFY_SSL
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error starting scheduled discovery task: %s", e, exc_info=True)
        return

    logging.info("Scheduled discovery STARTED successfully. HTTP response code: %d", resp.status_code)

def get_discovery_task_status(task_ref):
    """
    Fetch the 'state' and 'status' for the given discovery task ref.
    Returns (state, status_msg) or (None, None) if not found or error.
    """
    url = f"{BASE_URL}/discoverytask?_return_as_object=1&_return_fields%2B=status,state"

    try:
        resp = requests.get(url, auth=(USERNAME, PASSWORD), verify=VERIFY_SSL)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error retrieving discovery task status: %s", e, exc_info=True)
        return None, None

    data = resp.json()
    for task in data.get("result", []):
        if task.get("_ref") == task_ref:
            return task.get("state"), task.get("status")

    return None, None

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    scheduled_ref = get_scheduled_discovery_ref()
    if not scheduled_ref:
        print("Could not find 'scheduled' discovery reference. Check discovery.log for details.")
        return

    networks = get_discovery_enabled_networks()
    if networks:
        update_scheduled_discovery_task(scheduled_ref, networks)
    else:
        logging.info("No networks found to update for the scheduled discovery task.")

    # Optionally start the discovery (uncomment if desired)
    # start_scheduled_discovery_task(scheduled_ref)

    # Check final state
    state, status_msg = get_discovery_task_status(scheduled_ref)
    if state:
        logging.info("Scheduled Discovery State: %s", state)
    else:
        logging.warning("Could not retrieve state/status for the scheduled task.")

if __name__ == "__main__":
    try:
        main()
        print("Script finished successfully.")
    except Exception as ex:
        # Catch any top-level exceptions and log them
        logging.error("Unhandled exception in main(): %s", ex, exc_info=True)
        sys.exit(1)
