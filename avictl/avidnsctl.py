#!/usr/bin/env python3
import argparse
import os
import sys
from avi.sdk.avi_api import ApiSession
from requests.packages import urllib3
urllib3.disable_warnings()
import json
import re
from pathlib import Path

# Placeholder for actual API imports
# from avi.sdk.avi_api import ApiSession

CONFIG_PATH = os.path.join(os.getcwd(), "aviconfig.json")


def load_config(config_path):
    if not os.path.isfile(config_path):
        print(f"ERROR: Config file not found at: {config_path}\n")
        print(" Please create a aviconfig.json file in JSON format with following content:")
        print(json.dumps({
            "controller_ip": "192.168.1.100",
            "avi_version": "22.1.3",
            "username": "admin",
            "password": "yourpassword",
            "tenant": "admin",
            "dns_vs_name": "DNS-VS"
        }, indent=2))
        sys.exit(1)

    try:
        with open(config_path) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON format in config file: {config_path}")
        sys.exit(1)


def validate_config(config):
    required_keys = ["controller_ip", "api_version", "controller_username", "controller_password", "tenant", "dns_vs_name"]
    for key in required_keys:
        if key not in config:
            print(f"Missing required config key: {key}")
            sys.exit(1)

#Establish a first session with AVI Controller
def connect_api(config):
    api = ApiSession(
        controller_ip=config['controller_ip'],
        username=config['controller_username'],
        password=config['controller_password'],
        tenant=config['tenant'],
        api_version=config['api_version']
        )
    
    return(api)

# Extract DNS records from a given VS name
def get_dns_records (api: object, config: dict, list_records: bool):
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
        print('Error in GET request '+url_path+' :%s' % resp.text)

    # Print Result
    if (list_records):
      print_dns_records(resp_data[0])

    # Save Result
    return(resp_data[0])

# Print DNS Record information
def print_dns_records (vs_data: dict):
    """
    Print information of DNS records in a formatted table
    
    Parameters:
    -----------
    vs_data : dict
      The vs_data output   

    """ 
    print(f"{'ID':<2} {'FQDN':<25} {'IP Address':<15} {'TTL':<5} {'Type'}")
    print("-" * 60)

    # Print rows
    id=0
    if 'static_dns_records' in vs_data:
        for record in vs_data['static_dns_records']:
            fqdn = record.get('fqdn', [''])[0]
            ip = record.get('ip_address', [{}])[0].get('ip_address', {}).get('addr', '')
            ttl = record.get('ttl', '-')
            rec_type = record.get('type', '-')
            print(f"{id:<2} {fqdn:<25} {ip:<15} {ttl:<5} {rec_type}")
            id=id+1

def is_valid_fqdn(fqdn):
    # Must contain at least one dot and end with a valid TLD
    fqdn_regex = r'^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z]{2,})+$'
    return re.match(fqdn_regex, fqdn) is not None

def create_dns_record(api, config, fqdn, ip_address, ttl, type):
    if not fqdn or not ip_address or not ttl or not type:
        print("All parameters --fqdn, --ip_address, --ttl and --type are required.")
        sys.exit(1)
    
    if not is_valid_fqdn(fqdn):
        print(f"Invalid FQDN: '{fqdn}'. It must contain a domain like 'example.com'.")
        sys.exit(1)
    
    # Craft new object 
    new_dns_record= {
    'fqdn': [fqdn],
    'ip_address': [{
        'ip_address': {
            'addr': ip_address, 
            'type': 'V4'}
            }],
    'ttl': ttl,
    'type': type}
    
    list_records=False
    vs_data=get_dns_records(api, config, list_records)
    
    # Insert new entry into vs_data body
    if 'static_dns_records' in vs_data:
       vs_data['static_dns_records'].append(new_dns_record)
    else:
        vs_data['static_dns_records']=[new_dns_record]

    # Define PUT parameters
    url_path="virtualservice/"+vs_data["uuid"]

    print(f"Creating DNS record: {fqdn} -> {ip_address} {ttl} [{type}]")
    #Send BODY information via PUT
    resp = api.put (url_path, data=json.dumps(vs_data))

    if resp.status_code in range(200, 299):
        print('- Record '+fqdn+" created ", resp.reason)#, resp.text)
        print()
    else:
        print('Error in modifying '+url_path+' :%s' % resp.text)
        print()
    
    #Display new information
    get_dns_records(api, config, True)
    print()

def delete_dns_record(api, config, fqdn):
    if not fqdn:
        print("Parameter --fqdn is required.")
        sys.exit(1)
    
    if not is_valid_fqdn(fqdn):
        print(f"Invalid FQDN: '{fqdn}'. It must contain a domain like 'example.com'.")
        sys.exit(1)

    # Retrieve current vs information
    vs_data=get_dns_records(api, config, False)
    
    # Remove entry with particular FQDN
    if 'static_dns_records' in vs_data:
        original_count = len(vs_data["static_dns_records"])

        vs_data["static_dns_records"] = [
            record for record in vs_data["static_dns_records"]
            if record.get("fqdn", [None])[0] != fqdn
        ]

        new_count = len(vs_data["static_dns_records"])
        if original_count == new_count:
            print(f"- No DNS record found with FQDN: {fqdn}")
            sys.exit(1)
    else:
        print('-DNS virtualservice does not have any DNS Records. Nothing to do')
        sys.exit(1)

    # Define PUT parameters
    url_path="virtualservice/"+vs_data["uuid"]

    #Send BODY information via PUT
    resp = api.put (url_path, data=json.dumps(vs_data))

    if resp.status_code in range(200, 299):
          print('- Record '+fqdn+" deleted ", resp.reason)#, resp.text)
          print()
    else:
        print('Error in modifying '+url_path+' :%s' % resp.text)
    
    #Display new information
    get_dns_records(api, config, True)
    print()

def main():
    parser = argparse.ArgumentParser(
        prog='avidnsctl',
        description='AVI DNS Control Tool\n\nExamples:\n'
                    '  avidnsctl get dns_records\n'
                    '  avidnsctl create dns_record --fqdn test.example.com --ip_address 192.168.1.1\n'
                    '  avidnsctl delete dns_record --fqdn test.example.com',
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        '--config',
        help='Path to config file (default: ./aviconfig.json)',
        default='aviconfig.json'
    )

    subparsers = parser.add_subparsers(dest='command')

    # GET
    get_parser = subparsers.add_parser(
        'get',
        help='List DNS records'
    )
    get_parser.add_argument('resource', choices=['dns_records'], help='Resource type to list (only: dns_records)')

    # CREATE
    create_parser = subparsers.add_parser(
        'create',
        help='Create a new DNS record'
    )
    create_parser.add_argument('resource', choices=['dns_record'], help='Resource type to create (only: dns_record)')
    create_parser.add_argument('--fqdn', required=True, help='Fully qualified domain name (e.g., test.example.com)')
    create_parser.add_argument('--ip_address', required=True, help='IP address to associate (e.g., 192.168.1.1)')
    create_parser.add_argument('--ttl', type=int, default=5, help='TTL in minutes (default: 5)')
    create_parser.add_argument('--type', default='DNS_RECORD_A',
                               choices=['DNS_RECORD_A', 'DNS_RECORD_AAAA'],
                               help='Record type (default: DNS_RECORD_A)')

    # DELETE
    delete_parser = subparsers.add_parser(
        'delete',
        help='Delete a DNS record by FQDN'
    )
    delete_parser.add_argument('resource', choices=['dns_record'], help='Resource type to delete (only: dns_record)')
    delete_parser.add_argument('--fqdn', required=True, help='Fully qualified domain name to delete e.g. test.example.com')

    args = parser.parse_args()

    # Load config from default or user-specified path
    config = load_config(args.config)
    validate_config(config)
    api = connect_api(config)

    if args.command == 'get' and args.resource == 'dns_records':
        get_dns_records(api, config, True)
    elif args.command == 'create' and args.resource == 'dns_record':
        create_dns_record(
            api,
            config,
            fqdn=args.fqdn,
            ip_address=args.ip_address,
            ttl=args.ttl,
            type=args.type
        )
    elif args.command == 'delete' and args.resource == 'dns_record':
        delete_dns_record(api, config, args.fqdn)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
