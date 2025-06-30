import kopf
from avi.sdk.avi_api import ApiSession
import urllib3
import yaml
import re
import json
import datetime

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

def delete_dns_record(api, config, fqdn):
    if not fqdn:
        print("Parameter --fqdn is required.")

    # Retrieve current vs information
    vs_data=get_vs_config(api, config)

    # Remove entry with particular FQDN
    if 'static_dns_records' in vs_data:
        original_count = len(vs_data["static_dns_records"])

        vs_data["static_dns_records"] = [
            record for record in vs_data["static_dns_records"]
            if record.get("fqdn", [None])[0] != fqdn
        ]

        new_count = len(vs_data["static_dns_records"])
        if original_count == new_count:
            log(f"- No DNS record found with FQDN: {fqdn}")
    else:
        log('-DNS virtualservice does not have any DNS Records. Nothing to do')

    # Define PUT parameters
    url_path="virtualservice/"+vs_data["uuid"]

    #Send BODY information via PUT
    resp = api.put (url_path, data=json.dumps(vs_data))

    if resp.status_code in range(200, 299):
        log('- Record '+fqdn+" deleted ", resp.reason)#, resp.text)
    else:
        log('Error in modifying '+url_path+' :%s' % resp.text)

def update_dns_record(api, config, fqdn, ip_address, ttl, rtype):
    vs_data = get_vs_config(api, config)
    existing_records = vs_data.get("static_dns_records", [])

    # Verify if fqdn exists
    vs_data["static_dns_records"] = [
        rec for rec in existing_records
        if fqdn not in rec.get("fqdn", [])
    ]

    # Craft new object
    new_dns_record= {
    'fqdn': [fqdn],
    'ip_address': ip_address,
    'ttl': ttl,
    'type': rtype}

    # Ahora puedes añadir el nuevo sin riesgo de duplicados
    vs_data["static_dns_records"].append(new_dns_record)

    # Define PUT parameters
    url_path="virtualservice/"+vs_data["uuid"]
    body =  vs_data

    #Send BODY information via PUT
    resp = api.put (url_path, data=json.dumps(body))

    if resp.status_code in range(200, 299):
        log(resp)
        log('- Object '+url_path+' named '+body['name']+ " modified", resp.reason)#, resp.text)
    else:
        log('Error in modifying '+url_path+' :%s' % resp.text)

def create_dns_record(api, config, fqdn, ip_address, ttl, rtype):
    if not is_valid_fqdn(fqdn):
        log(f"Invalid FQDN: '{fqdn}'. It must contain a domain like 'example.com'.")
        sys.exit(1)

    # Craft new object
    new_dns_record= {
    'fqdn': [fqdn],
    'ip_address': ip_address,
    'ttl': ttl,
    'type': rtype}

    # Get current VS configuration
    vs_data=get_vs_config(api, config)

    # Insert new entry into vs_data body
    if 'static_dns_records' in vs_data:
       vs_data['static_dns_records'].append(new_dns_record)
    else:
        vs_data['static_dns_records']=[new_dns_record]

    # Define PUT parameters
    url_path="virtualservice/"+vs_data["uuid"]

    log(f"Creating DNS record: {fqdn} -> {ip_address} {ttl} [{rtype}]")
    #Send BODY information via PUT
    resp = api.put (url_path, data=json.dumps(vs_data))

    if resp.status_code in range(200, 299):
        log('Record '+fqdn+" created ", resp.reason)#, resp.text)
    else:
        log('Error in modifying '+url_path+' :%s' % resp.text)


def record_exists_in_vs(spec, vs_data):
    fqdn = spec["fqdn"]
    ip = spec.get("ip_address", [{}])[0]
    ttl = spec.get("ttl", 300)
    rtype = spec.get("rtype")

    for record in vs_data.get("static_dns_records", []):
        if fqdn in record.get("fqdn", []):
            if record.get("type") == rtype and record.get("ttl") == ttl:
                ip_list = record.get("ip_address", [])
                if any(entry.get("ip_address", {}).get("addr") == ip.get("addr") for entry in ip_list):
                    return True
    return False

def log(msg):
    timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S,%f]")[:-3]
    print(f"{timestamp} {msg}")


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

    create_dns_record(api, config, spec["fqdn"], spec.get("ip_address"), spec.get("ttl", 300), spec["rtype"])

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
def update_dnsrecord(spec, old, new, diff, **kwargs):
    config = load_config()
    patch.status['reconciled'] = False
    patch.status['sync_state'] = 'updating'

    fqdn = spec.get("fqdn")
    ip_address= spec.get("ip_address")
    ttl = spec.get("ttl", 300)
    rtype = spec.get("rtype")


    if not fqdn:
        raise kopf.PermanentError("Missing 'fqdn' in update.")

    api = ApiSession.get_session(
        controller_ip=config['controller_ip'],
        username=config['username'],
        password=config['password'],
        tenant=config.get('tenant', 'admin'),
        api_version=config.get('api_version')
    )

    update_dns_record(api, config, fqdn, ip_address, ttl, rtype)

################################################################################
#
# Reconcile 
#
# ################################################################################
@kopf.timer('akodns.vmware.com', 'v1', 'avidnsrecords', interval=300, sharp=True)
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
        print(f"[RECONCILE] Record {spec['fqdn']} not present or outdated. Re-applying...")
        update_dns_record(api, config, spec["fqdn"], spec["ip_address"], spec.get("ttl", 300), spec["rtype"])
    else:
        print(f"[RECONCILE] Record {spec['fqdn']} is in sync.")
    
    patch.status['last_synced'] = datetime.datetime.utcnow().isoformat() + "Z"
    patch.status['reconciled'] = True
    patch.status['sync_state'] = 'synced'
