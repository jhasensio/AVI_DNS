# Ancillary scripts for cloning existing AVI objects

#from avi.sdk.avi_api import ApiSession
from requests.packages import urllib3
urllib3.disable_warnings()
import json

# Display a menu from a given List and returns the selected option key
def display_menu_from_list (options, menu_title):  
    """
    Display a menu from a list of options and return the selected option.

    :param options: List of option descriptions.
    :param menu_title: String with Menu Title
    :return: The selected option (string) or None if the choice is invalid.
    """
    if not options:
        print("No options available.")
        return None

    print("\033[1m"+menu_title+"\033[0m")
    print("\033[1m--------------------------------------------------------------\033[0m")
    for index, option in enumerate(options, start=1):
        print(f"{index}. {option}")
    
    try:
        choice = int(input("Enter the number corresponding to your choice: "))
        if 1 <= choice <= len(options):
            return options[choice - 1]
        else:
            print()
            print("\033[1mInvalid choice. Please select a valid option.\033[0m")
            return None
    except ValueError:
        print()
        print("\033[1mInvalid input. Please enter a number.\033[0m")
        return None


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


# Extract DNS records from a given VS name
def extract_dns_records_from_vs (api: object, vs_name: dict) -> dict:
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
      "name": vs_name,
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
      resp_names = [resp_name["name"] for resp_name in resp_data]
      print("Getting information of " + url_path + " named:")
      print(resp_names)
      print()
    else:
        print('Error in GET request '+url_path+' :%s' % resp.text)

    # Save Result
    return(resp_data[0])
