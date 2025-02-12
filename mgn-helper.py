import boto3
import botocore
import argparse
import logging
import sys
import json
from tabulate import tabulate
import inquirer

DEFAULT_REGION = "eu-west-2"
should_save = False

def get_default_region():
    """Get the default AWS region from the current session or fallback to default."""
    session = boto3.session.Session()
    return session.region_name or DEFAULT_REGION

def save_to_file(data, filename, log_message):
    """Save data to a JSON file with proper formatting."""
    if not data:
        logging.warning(f"No {log_message} found.")
        return
    with open(filename, "w") as file:
        json.dump(data, file, indent=4, default=str)
    logging.info(f"Saved {log_message} to {filename}")

def parse_arguments(default_region):
    """Set up and parse command-line arguments with descriptive help messages."""
    parser = argparse.ArgumentParser(description="AWS MGN Automation Script")
    parser.add_argument("-r", "--region", type=str, default=default_region, 
                       help=f"AWS region to use (default: {default_region})")
    parser.add_argument("-v", "--verbose", action="count", default=0, 
                       help="Increase verbosity level (use -v for INFO, -vv for DEBUG)")
    parser.add_argument("-s", "--save-to-file", action="store_true", default=False, 
                       help="Save results to file")
    parser.add_argument("-g", "--generate-tf", action="store_true", default=False, 
                       help="Generate Terraform files for servers")
    return parser.parse_args()

def setup_logging(verbose):
    """Configure logging with appropriate level and handlers."""
    level = [logging.WARNING, logging.INFO, logging.DEBUG][min(verbose, 2)]
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=level,
        handlers=[logging.StreamHandler(), logging.FileHandler("mgn_logs.log", mode="w")]
    )

def initialize_aws_clients(region):
    """Initialize AWS clients with proper error handling."""
    try:
        logging.info(f"Initializing AWS clients in {region} ...")
        return (
            boto3.client("mgn", region_name=region),
            boto3.client("ec2", region_name=region)
        )
    except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as e:
        logging.error(f"Error initializing AWS clients: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error initializing AWS clients: {e}")
        sys.exit(1)

def fetch_paginated_results(client, method, result_key, **kwargs):
    """Generic function to handle AWS pagination."""
    paginator = client.get_paginator(method)
    results = []
    for page in paginator.paginate(**kwargs):
        results.extend(page.get(result_key, []))
    return results

def list_applications(mgn_client):
    """Fetch and process MGN applications."""
    try:
        logging.info("Fetching applications from AWS MGN...")
        applications = fetch_paginated_results(mgn_client, 'list_applications', 'items')
        logging.info(f"Retrieved {len(applications)} applications.")
        if should_save:
            save_to_file(applications, "mgn_applications.json", "applications")
        return applications
    except Exception as e:
        logging.error(f"Error retrieving applications: {e}")
        return []

def list_source_servers(mgn_client):
    """Fetch and process MGN source servers."""
    try:
        logging.info("Fetching source servers from AWS MGN...")
        source_servers = fetch_paginated_results(mgn_client, 'describe_source_servers', 'items', 
                                               filters={'isArchived': False})
        logging.info(f"Retrieved {len(source_servers)} source servers.")
        if should_save:
            save_to_file(source_servers, "mgn_source_servers.json", "source servers")
        return source_servers
    except Exception as e:
        logging.error(f"Error retrieving source servers: {e}")
        return []

def get_launch_configurations(mgn_client, servers):
    """Fetch and process launch configurations for non-archived servers."""
    try:
        logging.info("Fetching launch configurations from AWS MGN...")
        launch_configs = []
        for server in servers:
            if not server.get("isArchived", False):
                source_server_id = server.get("sourceServerID")
                response = mgn_client.get_launch_configuration(sourceServerID=source_server_id)
                launch_configs.append(response)
                server['Launch Configuration'] = response
        logging.info(f"Retrieved {len(launch_configs)} launch configurations.")
        if should_save:
            save_to_file(launch_configs, "mgn_launch_configurations.json", "launch configurations")
        return launch_configs
    except Exception as e:
        logging.error(f"Error retrieving launch configurations: {e}")
        return []

def get_launch_templates(ec2_client, servers):
    """Fetch and process EC2 launch templates."""
    try:
        logging.info("Fetching launch templates from AWS EC2...")
        launch_templates = []
        for server in servers:
            launch_template_id = server.get("Launch Configuration", {}).get("ec2LaunchTemplateID")
            response = ec2_client.describe_launch_template_versions(
                LaunchTemplateId=launch_template_id, 
                Versions=["$Default"]
            )
            server['Launch Template'] = response
            launch_templates.append(response)
        logging.info(f"Retrieved {len(launch_templates)} launch templates.")
        if should_save:
            save_to_file(launch_templates, "mgn_launch_templates.json", "launch templates")
        return launch_templates
    except Exception as e:
        logging.error(f"Error retrieving launch templates: {e}")
        return []

def get_subnets(ec2_client):
    """Fetch and process EC2 subnets."""
    try:
        logging.info("Fetching subnets from AWS EC2...")
        subnets = fetch_paginated_results(ec2_client, 'describe_subnets', 'Subnets')
        logging.info(f"Retrieved {len(subnets)} subnets.")
        if should_save:
            save_to_file(subnets, "ec2_subnets.json", "subnets")
# KEEP FOR REFERENCE: Create a dictionary of subnet IDs and names
        # subnet_dict = {
        #     subnet["SubnetId"]: next((tag["Value"] for tag in subnet["Tags"] if tag["Key"] == "Name"), "Unknown Name")
        #     for subnet in subnets
        # }
        # print(subnet_dict)
        return subnets
    except Exception as e:
        logging.error(f"Error retrieving subnets: {e}")
        return []

def get_security_groups(ec2_client):
    """Fetch and process EC2 security groups."""
    try:
        logging.info("Fetching security groups from AWS EC2...")
        security_groups = fetch_paginated_results(ec2_client, 'describe_security_groups', 'SecurityGroups')
        logging.info(f"Retrieved {len(security_groups)} security groups.")
        if should_save:
            save_to_file(security_groups, "ec2_security_groups.json", "security groups")
        return security_groups
    except Exception as e:
        logging.error(f"Error retrieving security groups: {e}")
        return []

# Not required for now, but will be useful for future enhancements
# def select_servers(servers):
#     """Allow user to select specific servers interactively."""
#     questions = [
#         inquirer.Checkbox(
#             'selected_servers',
#             message="Select servers to generate Terraform files for",
#             choices=[f"{server['sourceServerID']} - {server['tags'].get('Name', 'Unknown')}" for server in servers]
#         )
#     ]
#     answers = inquirer.prompt(questions)
#     selected_ids = [answer.split(" - ")[0] for answer in answers['selected_servers']]
#     return [server for server in servers if server['sourceServerID'] in selected_ids]

def extract_server_details(server):
    """Extract and format server details for display."""
    launch_template = server.get("Launch Template", {}).get("LaunchTemplateVersions", [{}])[0]
    launch_template_data = launch_template.get('LaunchTemplateData', {})
    network_interface = launch_template_data.get('NetworkInterfaces', [{}])[0]

    return {
        'Name': server.get('tags', {}).get('Name', 'Unknown'),
        'State': server.get('lifeCycle', {}).get('state', 'N/A'),
        'Instance Type': server.get('sourceProperties', {}).get('recommendedInstanceType', 'none'),
        'Volumes': [
            f"{volume.get('DeviceName', 'none')}={volume.get('Ebs', {}).get('VolumeSize', 'none')}"
            for volume in launch_template_data.get('BlockDeviceMappings', [])
        ],
        'Instance Profile': (launch_template_data.get('IamInstanceProfile', {}).get('Arn', 'none').split('/')[-1]),
        'Subnet': network_interface.get('SubnetId', 'none'),
        'Sgs': network_interface.get('Groups', []),
        'Termination Protection': launch_template_data.get('DisableApiTermination', 'none')
    }

def format_table_data(target_servers):
    """Format server details into a tabulated display."""
    try:
        # Column configuration with shortened headers for better readability
        columns = {
            'Name': 'Name', 
            'State': 'State', 
            'Instance Type': 'I.Type',
            'Volumes': 'Volumes', 
            'Instance Profile': 'I.Profile',
            'Subnet': 'Subnet', 
            'Sgs': 'SGs', 
            'Termination Protection': 'T.Prot'
        }
        
        headers = list(columns.values())
        table_data = [[server[k] for k in columns.keys()] for server in target_servers]
        
        return tabulate(
            table_data,
            headers=headers,
            tablefmt='grid',
            maxcolwidths=[20, 20, 10, 15, 15, 15, 24, 8],
            stralign='left'
        )
    except Exception as e:
        logging.error(f"Error formatting table data: {e}")
        return "Error formatting server details"

def collect_aws_resources(mgn_client, ec2_client):
    """Collect all required AWS resources in a structured way."""
    resources = {}
    
    resources['applications'] = list_applications(mgn_client)
    resources['servers'] = list_source_servers(mgn_client)
    
    if resources['servers']:
        resources['launch_configs'] = get_launch_configurations(mgn_client, resources['servers'])
        resources['launch_templates'] = get_launch_templates(ec2_client, resources['servers'])
    else:
        logging.warning("No servers found, skipping launch configurations and templates")
        resources['launch_configs'] = []
        resources['launch_templates'] = []
    
    resources['subnets'] = get_subnets(ec2_client)
    resources['security_groups'] = get_security_groups(ec2_client)
    
    return resources

def verify_aws_access(region):
    """Verify AWS credentials and region access before proceeding."""
    try:
        # Test if we can access AWS by making a simple API call
        test_client = boto3.client('sts', region_name=region)
        test_client.get_caller_identity()
        logging.info(f"Successfully verified AWS credentials for region {region}")
        return True
    except botocore.exceptions.ClientError as e:
        if "AccessDenied" in str(e):
            logging.error("AWS credentials are invalid or have insufficient permissions")
        elif "ExpiredToken" in str(e):
            logging.error("AWS credentials have expired")
        else:
            logging.error(f"AWS access error: {e}")
        return False
    except botocore.exceptions.NoCredentialsError:
        logging.error("No AWS credentials found. Please configure your AWS credentials")
        return False
    except Exception as e:
        logging.error(f"Unexpected error verifying AWS access: {e}")
        return False

def main():
    global should_save
    default_region = get_default_region()
    args = parse_arguments(default_region)
    should_save = args.save_to_file
    setup_logging(args.verbose)
    
    try:
        # Verify AWS access before proceeding
        if not verify_aws_access(args.region):
            sys.exit(1)
            
        mgn_client, ec2_client = initialize_aws_clients(args.region)
        
        # Collect all AWS resources
        logging.info(f"Starting AWS resource collection in region {args.region}")
        resources = collect_aws_resources(mgn_client, ec2_client)
        
        if not resources['servers']:
            logging.error("No source servers found in MGN")
            sys.exit(1)
            
        # Not required for now, but will be useful for future enhancements
        # if args.generate_tf:
        #     generate_for_all = inquirer.confirm("Generate Terraform files for all servers?", default=True)
        #     if generate_for_all:
        #         selected_servers = resources['servers']
        #     else:
        #         selected_servers = select_servers(resources['servers'])
        #     print(f"Selected servers for Terraform generation: {[server['sourceServerID'] for server in selected_servers]}")

        # Process and display server details
        target_servers = [extract_server_details(server) for server in resources['servers']]
        table_output = format_table_data(target_servers)
        print("\nServer Details:")
        print(table_output)
        
        if should_save:
            logging.info("All data has been saved to respective JSON files")
            
    except KeyboardInterrupt:
        logging.info("Operation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
