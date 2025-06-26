
ctrl_version = "22.1.6"
session_params = {
    'name' : 'avicontroller',
    'controller_username': "admin",
    'controller_password': "VMware1!",
    'controller_ip': "192.168.1.15",
    'controller_domain_name': 'avicontroller.sdefinitive.local',
    'tenant': "admin",
    'api_version': ctrl_version,
    'cloud': "Default-Cloud", # Name of NSX-T Cloud Integration as defined in the controller configuration
    'se_group': "Default-Group",
    'headers': {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'X-AVI-VERSION': ctrl_version
            }
}