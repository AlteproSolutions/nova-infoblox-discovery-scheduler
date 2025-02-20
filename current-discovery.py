#!/usr/bin/env python3
"""
Current Discovery Script for Infoblox

This script immediately updates and restarts the current discovery task.
It accepts a required argument (--network_view or -nv) to specify the network view
to filter networks by and an optional flag (--force or -f) to automatically stop 
a running/paused discovery without prompting (useful for cron jobs).
It then:
  - Retrieves network objects with 'Network_Discovery' set to True,
  - Filters them based on the provided view,
  - Checks if the current discovery task is RUNNING, PAUSED, or END_PENDING and, if so,
    prompts the user (unless --force is used) to stop it completely,
  - Sends an "END" action to fully end the current discovery and waits until the state 
    is no longer RUNNING, PAUSED, or END_PENDING,
  - Updates the current discovery task with the filtered network references,
  - And starts a new discovery with a "START" action.
  
All events are logged to 'discovery.log' with each log entry prefixed by "CURRENT_DISCOVERY_SCRIPT".
"""

import argparse
import ipaddress
import json
import logging
import os
import requests
import sys
import time
import yaml
from urllib.parse import urlparse

# -----------------------------------------------------------------------------
# SCRIPT TYPE FOR LOGGING
# -----------------------------------------------------------------------------
SCRIPT_TYPE = "CURRENT_DISCOVERY_SCRIPT"

# -----------------------------------------------------------------------------
# LOGGING SETUP
# -----------------------------------------------------------------------------
logging.basicConfig(
    filename='discovery.log',
    level=logging.INFO,
    format=f'%(asctime)s {SCRIPT_TYPE} %(levelname)s %(message)s'
)

def validate_config(cfg):
    """
    Validate required configuration fields for Infoblox current discovery.
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

def parse_args():
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Immediate discovery update tool for Infoblox current discovery."
    )
    parser.add_argument(
        "--network_view", "-nv",
        required=True,
        help="The network view to filter networks by (e.g., 'default' or 'GLOBAL')."
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Automatically stop current discovery without prompting (useful for cron jobs)."
    )
    return parser.parse_args()

# -----------------------------------------------------------------------------
# LOAD CONFIGURATION FROM YAML
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
CONFIG_DEFAULT_VIEW = config.get("SCHEDULED_DISCOVERY_NETWORK_VIEW", "default")
SCHEDULED_DISCOVERY_DEFAULT_NETWORK = config.get("SCHEDULED_DISCOVERY_DEFAULT_NETWORK", "")

WAPI_VERSION = "v2.12"
VERIFY_SSL   = False
if not VERIFY_SSL:
    requests.packages.urllib3.disable_warnings()
BASE_URL = f"{INFOBLOX_API_URL}/wapi/{WAPI_VERSION}"

def get_current_discovery_ref():
    """
    Retrieve the current discovery task reference (discovery_task_oid == "current").
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
        if task.get("discovery_task_oid") == "current":
            logging.info("Found current discovery task ref: %s", task["_ref"])
            return task["_ref"]
    logging.warning("No current discovery task found.")
    return None

def get_current_discovery_status(task_ref):
    """
    Retrieve the state and status of the current discovery task.
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

def get_discovery_enabled_networks():
    """
    Retrieve all network objects with 'Network_Discovery' set to True.
    """
    url = f"{BASE_URL}/network?_return_fields=network,extattrs&_return_as_object=1&_max_results=1000000"
    try:
        r = requests.get(url, auth=(USERNAME, PASSWORD), verify=VERIFY_SSL)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error retrieving network objects: %s", e, exc_info=True)
        return []
    data = r.json()
    found = []
    for net in data.get("result", []):
        extattrs = net.get("extattrs", {})
        if extattrs.get("Network_Discovery", {}).get("value") == "True":
            found.append(net["_ref"])
    logging.info("Found %d networks with Network_Discovery=True", len(found))
    return found

def filter_by_view(network_refs, desired_view):
    """
    Filter network references to only those ending with '/<desired_view>'.
    """
    suffix = f"/{desired_view}"
    return [ref for ref in network_refs if ref.endswith(suffix)]

def get_network_ref(network_cidr, network_view):
    """
    Retrieve the network object _ref for the given network CIDR and network view.
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

def stop_current_discovery_task(task_ref):
    """
    End the current discovery task by sending an END action.
    Returns True on success, False otherwise.
    """
    url = f"{BASE_URL}/{task_ref}?_function=network_discovery_control"
    headers = {"Content-Type": "application/json"}
    payload = {"action": "END"}
    logging.info("Stopping current discovery (END): %s", task_ref)
    try:
        r = requests.post(url, auth=(USERNAME, PASSWORD), headers=headers, data=json.dumps(payload), verify=VERIFY_SSL)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error ending current discovery: %s", e, exc_info=True)
        return False
    logging.info("Current discovery ended successfully. HTTP response code: %d", r.status_code)
    return True

def wait_for_discovery_to_stop(task_ref, timeout=60, interval=5):
    """
    Wait until the current discovery task is no longer RUNNING, PAUSED, or END_PENDING.
    Returns True if the task stops within the timeout, False otherwise.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        state, _ = get_current_discovery_status(task_ref)
        if state and state.upper() not in ("RUNNING", "PAUSED", "END_PENDING"):
            return True
        logging.info("Waiting for discovery to stop. Current state: %s", state)
        time.sleep(interval)
    return False

def update_current_discovery_task(task_ref, network_refs, mode="ICMP", ping_retries=5, ping_timeout=1500):
    """
    Overwrite the current discovery task with the provided network references.
    Returns True on success, False on failure.
    """
    url = f"{BASE_URL}/{task_ref}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "mode": mode,
        "network_view": desired_view,  # use the view from the command-line argument
        "networks": network_refs,
        "ping_retries": ping_retries,
        "ping_timeout": ping_timeout
    }
    logging.info("Updating current discovery '%s' with %d networks in view '%s'.", task_ref, len(network_refs), desired_view)
    try:
        r = requests.put(url, auth=(USERNAME, PASSWORD), headers=headers, data=json.dumps(payload), verify=VERIFY_SSL)
        r.raise_for_status()
        logging.info("Current discovery updated successfully. HTTP code: %d", r.status_code)
        return True
    except requests.exceptions.RequestException as e:
        logging.error("Error updating current discovery with new networks: %s", e, exc_info=True)
        return False

def start_current_discovery_task(task_ref):
    """
    Completely stop the current discovery task and then start a new discovery.
    Returns True on success, False otherwise.
    """
    state, _ = get_current_discovery_status(task_ref)
    if state and state.upper() in ("RUNNING", "PAUSED", "END_PENDING"):
        logging.info("Current discovery is %s; attempting to end it.", state.upper())
        if not stop_current_discovery_task(task_ref):
            logging.error("Failed to end the current discovery task.")
            return False
        if not wait_for_discovery_to_stop(task_ref):
            logging.error("Timed out waiting for discovery to end.")
            return False
    else:
        logging.info("Current discovery state is '%s'. Proceeding to start.", state)

    # Now start a new discovery
    url = f"{BASE_URL}/{task_ref}?_function=network_discovery_control"
    headers = {"Content-Type": "application/json"}
    payload = {"action": "START"}
    logging.info("Starting current discovery: %s", task_ref)
    try:
        r = requests.post(url, auth=(USERNAME, PASSWORD), headers=headers, data=json.dumps(payload), verify=VERIFY_SSL)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error("Error starting current discovery: %s", e, exc_info=True)
        return False
    logging.info("Current discovery started successfully. HTTP response code: %d", r.status_code)
    time.sleep(5)
    new_state, _ = get_current_discovery_status(task_ref)
    if new_state and new_state.upper() == "RUNNING":
        logging.info("Current discovery is now RUNNING.")
        return True
    else:
        logging.error("Current discovery failed to start. Final state: %s", new_state)
        return False

def prompt_overwrite(force):
    """
    Prompt the user to decide if the currently running or paused discovery should be stopped.
    If force is True, automatically return True without prompting.
    Returns True if the user answers 'y' or if force is True, False otherwise.
    """
    if force:
        return True
    answer = input("Current discovery is running or paused. Do you want to stop it and run a new discovery? (y/n): ").strip().lower()
    return answer == 'y'

def main():
    """
    Main function for updating and restarting the current discovery task.
    """
    logging.info("CURRENT_DISCOVERY_SCRIPT: Script started.")
    global desired_view  # set by command-line argument
    args = parse_args()
    desired_view = args.network_view
    force_overwrite = args.force

    current_ref = get_current_discovery_ref()
    if not current_ref:
        print("Could not find 'current' discovery reference. Check discovery.log for details.")
        return

    state, _ = get_current_discovery_status(current_ref)
    if state:
        logging.info("Current discovery state: %s", state)
        print(f"Current discovery state: {state}")
        if state.upper() in ("RUNNING", "PAUSED", "END_PENDING"):
            if not prompt_overwrite(force_overwrite):
                print("Aborting update. Current discovery is still running/paused.")
                return
    else:
        logging.warning("Could not retrieve status for current discovery. Proceeding with update...")

    discovered = get_discovery_enabled_networks()
    if discovered:
        filtered = filter_by_view(discovered, desired_view)
        if filtered:
            networks = filtered
            logging.info("After filtering by view '%s', %d networks remain out of %d discovered.",
                         desired_view, len(filtered), len(discovered))
        else:
            logging.info("Discovered %d networks, but none match view '%s'.", len(discovered), desired_view)
            networks = []
    else:
        logging.info("No networks found with Network_Discovery=True.")
        networks = []

    if not networks:
        print(f"No networks found matching view '{desired_view}'. Update skipped.")
        return

    success = update_current_discovery_task(current_ref, networks)
    if not success:
        print("An error occurred while updating the current discovery. Please check discovery.log.")
        return

    if start_current_discovery_task(current_ref):
        print("Current discovery started successfully.")
    else:
        print("An error occurred while starting current discovery. Please check discovery.log.")

    state, _ = get_current_discovery_status(current_ref)
    if state:
        logging.info("Final Current Discovery State: %s", state)
        print(f"Final Current Discovery State: {state}")
    else:
        logging.warning("Could not retrieve final status for the current discovery task.")
        print("Could not retrieve final discovery status. Check discovery.log for details.")
    
    logging.info("CURRENT_DISCOVERY_SCRIPT: Script finished successfully.")

if __name__ == "__main__":
    try:
        main()
        print("Script finished successfully.")
    except Exception as ex:
        logging.error("Unhandled exception in main(): %s", ex, exc_info=True)
        sys.exit(1)
