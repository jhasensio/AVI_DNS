import kopf
from avi.sdk.avi_api import ApiSession
import urllib3
import yaml
import re
import json
import datetime
import time

urllib3.disable_warnings()

def load_config():
    config = {}
    with open("/config/controller_config.yaml") as f:
        config.update(yaml.safe_load(f))
    with open("/config/controller_secret.yaml") as f:
        config.update(yaml.safe_load(f))
    return config

def is_valid_fqdn(fqdn):
    # Must contain at least one dot and end with a valid TLD
    fqdn_regex = r'^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z]{2,})+$'
    return re.match(fqdn_regex, fqdn) is not None

# Extract VS DNS information records from a given VS name
def get_vs_config (api: object, config: dict):
    """
    Extract information of a given Service Engine Group

    Parameters:
    -----------
    api : avi.sdk.avi_api.ApiSession
      The AVI ApiSession object containing session paramenters to use AVI API

    vs_name : string
      The vs name of interest

    Returns:
    --------
    dict
      Dictionary containing virtualservice object output

    """

    # Define GET request parameters
    url_path = "virtualservice"
    query = {
      "skip_default": "true",
      "name": config['dns_vs_name'],
      "include_name": "true"
    }
    # Send GET Request
    resp = api.get(url_path, params=query)


    # Control Response Status Code
    if resp.status_code in range(200, 299):

      # Convert response JSON into Python Dictionary
      resp_data = json.loads(resp.text)

      # Extract Result
      resp_data = resp_data["results"]
    else:
        log('Error in GET request '+url_path+' :%s' % resp.text)

    # Save Result
    return(resp_data[0])


def patch_vs_with_retries(api, config, mutate_fn, max_retries=3, backoff=1):
    """
    Repeatedly:
      1) GET the latest VS
      2) Call mutate_fn(vs) → new_vs_body
      3) PUT the new body
    until success or max_retries.
    If still failing, raises TemporaryError for Kopf to retry later.
    """
    for attempt in range(1, max_retries + 1):
        vs = get_vs_config(api, config)              # freshest copy
        body = mutate_fn(vs.copy())                  # let caller apply their patch
        resp = api.put(f"virtualservice/{vs['uuid']}",
                       data=json.dumps(body))
        text = (resp.text or "")
        if 200 <= resp.status_code < 300:
            return resp
        if "Concurrent Update Error" in text and attempt < max_retries:
            time.sleep(backoff)
            continue
        # non-retryable or out of attempts → hand off to Kopf
        raise kopf.TemporaryError(f"VS update failed: {text}", delay=backoff)

    # unreachable
    raise kopf.TemporaryError("VS retry loop failed unexpectedly", delay=backoff)

def create_dns_record(api, config, fqdn, ip_address, ttl, rtype, delegated, algorithm, wildcard_match):
    def patch_fn(vs):
        existing = { r['fqdn'][0] for r in vs.get('static_dns_records', []) }
        if fqdn not in existing:
            vs.setdefault('static_dns_records', []).append({
                'fqdn':      [fqdn],
                'ip_address': ip_address,
                'ttl':        ttl,
                'type':       rtype,
                'delegated':  delegated,
                'algorithm':  algorithm,
                'wildcard_match': wildcard_match
            })
        return vs

    log(f"Creating DNS record: {fqdn} -> {ip_address} {ttl} [{rtype}]")
    try:
        patch_vs_with_retries(api, config, patch_fn)
        log("Record created successfully.")
    except kopf.TemporaryError as e:
        # Kopf will automatically retry the handler after e.delay
        raise

def update_dns_record(api, config, fqdn, ip_address, ttl, rtype, delegated, algorithm, wildcard_match):
    def patch_fn(vs):
        # remove any existing for this fqdn
        vs['static_dns_records'] = [
            rec for rec in vs.get('static_dns_records', [])
            if fqdn not in rec.get('fqdn', [])
        ]
        # add the new one
        vs['static_dns_records'].append({
            'fqdn':      [fqdn],
            'ip_address': ip_address,
            'ttl':       ttl,
            'type':      rtype,
            'delegated':  delegated,
            'algorithm':  algorithm,
            'wildcard_match': wildcard_match
        })
        return vs

    log(f"Updating DNS record: {fqdn}")
    patch_vs_with_retries(api, config, patch_fn)
    log("Record updated successfully.")

def delete_dns_record(api, config, fqdn):
    def patch_fn(vs):
        vs['static_dns_records'] = [
            rec for rec in vs.get('static_dns_records', [])
            if rec.get('fqdn', [None])[0] != fqdn
        ]
        return vs

    log(f"Deleting DNS record: {fqdn}")
    patch_vs_with_retries(api, config, patch_fn)
    log("Record deleted successfully.")


def record_exists_in_vs(spec, vs_data):
    fqdn = spec["fqdn"]
    ip = spec.get("ip_address", [{}])[0]
    ttl = spec.get("ttl", 300)
    rtype = spec.get("rtype")
    delegated = spec.get("delegated", False)
    algorithm = spec.get("algorithm", "DNS_RECORD_RESPONSE_ROUND_ROBIN")
    wildcard_match = spec.get("wildcard_match", False)

    for record in vs_data.get("static_dns_records", []):
        if fqdn in record.get("fqdn", []):
            if record.get("type") == rtype and record.get("ttl") == ttl and record.get("delegated")==delegated and record.get("algorithm")==algorithm and record.get("wildcard_match")==wildcard_match:
                ip_list = record.get("ip_address", [])
                if any(entry.get("ip_address", {}).get("addr") == ip.get("addr") for entry in ip_list):
                    return True
    return False

def log(*parts):
    """
    Accepts any number of arguments, converts each to str, and joins them with spaces.
    """
    timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S,%f]")[:-3]
    message = " ".join(str(p) for p in parts)
    print(f"{timestamp} {message}")

################################################################################
#
# Trigger DNS record creation when a new avidnsrecord object is CREATED
#
# ################################################################################
@kopf.on.create('akodns.vmware.com', 'v1', 'avidnsrecords')
def create_dnsrecord(spec, status, patch, **kwargs):
    config = load_config()
    patch.status['reconciled'] = False
    patch.status['sync_state'] = 'creating'

    api = ApiSession.get_session(
        controller_ip=config['controller_ip'],
        username=config['username'],
        password=config['password'],
        tenant=config.get('tenant', 'admin'),
        api_version=config.get('api_version')
    )

    create_dns_record(api, config, spec["fqdn"], spec.get("ip_address"), spec.get("ttl", 300), spec["rtype"], spec.get("delegated", False), spec.get("algorithm", "DNS_RECORD_RESPONSE_ROUND_ROBIN"), spec.get("wildcard_match", False))
    patch.status['reconciled']  = True
    patch.status['sync_state']  = 'synced'
    patch.status['last_synced'] = datetime.datetime.utcnow().isoformat() + "Z"


################################################################################
#
# Trigger DNS record creation when a new avidnsrecord object is DELETED
#
# ################################################################################
@kopf.on.delete('akodns.vmware.com', 'v1', 'avidnsrecords')
def delete_dnsrecord(spec, **kwargs):
    config = load_config()

    fqdn = spec.get("fqdn")

    if not fqdn:
        raise kopf.PermanentError("Missing 'fqdn' in delete.")

    api = ApiSession.get_session(
        controller_ip=config['controller_ip'],
        username=config['username'],
        password=config['password'],
        tenant=config.get('tenant', 'admin'),
        api_version=config.get('api_version')
    )

    delete_dns_record(api, config, fqdn)

################################################################################
#
# Trigger DNS record creation when a new avidnsrecord object is UPDATED
#
# ################################################################################
@kopf.on.update('akodns.vmware.com', 'v1', 'avidnsrecords')
def update_dnsrecord(spec, old, new, diff, status, patch, **kwargs):
    config = load_config()
    patch.status['reconciled'] = False
    patch.status['sync_state'] = 'updating'

    fqdn = spec["fqdn"]

    if not fqdn:
        raise kopf.PermanentError("Missing 'fqdn' in update.")

    api = ApiSession.get_session(
        controller_ip=config['controller_ip'],
        username=config['username'],
        password=config['password'],
        tenant=config.get('tenant', 'admin'),
        api_version=config.get('api_version')
    )

    update_dns_record(api, config, spec["fqdn"], spec.get("ip_address"), spec.get("ttl", 300), spec["rtype"], spec.get("delegated", False), spec.get("algorithm", "DNS_RECORD_RESPONSE_ROUND_ROBIN"), spec.get("wildcard_match", False))

    patch.status['reconciled']  = True
    patch.status['sync_state']  = 'synced'
    patch.status['last_synced'] = datetime.datetime.utcnow().isoformat() + "Z"


################################################################################
#
# Reconcile
#
# ################################################################################
@kopf.timer('akodns.vmware.com', 'v1', 'avidnsrecords', interval=120, sharp=False, initial_delay=30)
def reconcile_periodically(spec, status, patch, meta, **kwargs):
    if status.get("reconciled") is False or status.get("sync_state") in ["creating", "updating"]:
        print(f"⏱️ [{meta['name']}] Skipping reconciliation (still in transition).")
        return

    config = load_config()
    api = ApiSession.get_session(
        controller_ip=config['controller_ip'],
        username=config['username'],
        password=config['password'],
        tenant=config.get('tenant', 'admin'),
        api_version=config.get('api_version')
    )

    vs_data = get_vs_config(api, config)

    if not record_exists_in_vs(spec, vs_data):
        log(f"[RECONCILE] Record {spec['fqdn']} not present or outdated. Re-applying...")
        update_dns_record(api, config, spec["fqdn"], spec.get("ip_address"), spec.get("ttl", 300), spec["rtype"], spec.get("delegated", False), spec.get("algorithm", "DNS_RECORD_RESPONSE_ROUND_ROBIN"), spec.get("wildcard_match", False))
    else:
        log(f"[RECONCILE] Record {spec['fqdn']} is in sync.")

    patch.status['last_synced'] = datetime.datetime.utcnow().isoformat() + "Z"
    patch.status['reconciled'] = True
    patch.status['sync_state'] = 'synced'