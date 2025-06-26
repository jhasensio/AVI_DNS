import kopf
from avi.sdk.avi_api import ApiSession
import urllib3
import yaml

urllib3.disable_warnings()

def load_config():
    config = {}
    with open("/config/controller_config.yaml") as f:
        config.update(yaml.safe_load(f))
    with open("/config/controller_secret.yaml") as f:
        config.update(yaml.safe_load(f))
    return config

@kopf.on.create('akodns.vmware.com', 'v1', 'avidnsrecords')
def create_dnsrecord(spec, **kwargs):
    config = load_config()

    session = ApiSession.get_session(
        controller_ip=config['controller_ip'],
        username=config['username'],
        password=config['password'],
        tenant=config.get('tenant', 'admin'),
        api_version=config.get('api_version')
    )

    payload = {
        "name": spec['fqdn'],
        "fqdn": spec['fqdn'],
        "ttl": spec.get('ttl', 300),
        "type": spec['type'],
        "a_records": spec.get('a_records'),
        "cname": spec.get('cname'),
    }

    response = session.post(config['api_path'], data=payload)

    return {
        'status': response.status_code,
        'reason': response.text
    }
