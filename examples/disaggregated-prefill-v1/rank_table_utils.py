"""RANK_TABLE Configuration Utility Script"""
import json
import os
import socket
import sys
from argparse import ArgumentParser
from typing import Dict, Any

def parse_args():
    """
    Parse command line arguments for RANK_TABLE utility

    Returns:
        args: Parsed command line arguments
    """
    parser = ArgumentParser(description="RANK_TABLE Configuration Utility - Generate and merge RANK_TABLE config files")

    # Common arguments
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.default = 'generate'
    
    # Generate command
    gen_parser = subparsers.add_parser('generate', help='Generate single RANK TABLE config file')
    gen_parser.add_argument("--device_num", type=str, default="[0,16)",
                          help="The number of the Ascend accelerators used. Must be continuous, e.g. [0,4) means using chips 0,1,2,3")
    gen_parser.add_argument("--visible_devices", type=str, default="0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
                          help="The visible devices according to the software system")
    gen_parser.add_argument("--server_ip", type=str, default="127.0.0.1",
                          help="Set the server_ip manually, to avoid errors in auto detection")
    gen_parser.add_argument("--instance_role", type=str, default="prefill",
                          help="Set the instance role, prefill or decode")
    gen_parser.add_argument("--instance_rank", type=int, default=0,
                          help="Set the instance rank")
    gen_parser.add_argument("--num_instances", type=int, default=1,
                          help="Set the number of instances")
    gen_parser.add_argument("--output_dir", type=str, default=os.getcwd(),
                          help="Directory to save the generated rank_table config file")

    # Merge command
    merge_parser = subparsers.add_parser('merge', help='Merge multiple RANK_TABLE config files')
    merge_parser.add_argument("file_list", type=str, nargs="+", help="RANK_TABLE file lists to merge")
    merge_parser.add_argument("--output_dir", type=str, default=os.getcwd(),
                            help="Directory to save the merged rank_table config file")

    return parser.parse_args()

def get_host_ip():
    """
    Get host IP address

    Returns:
        str: Host IP address
    """
    try:
        hostname = socket.gethostname()
        return socket.gethostbyname(hostname)
    except:
        return None

def generate_rank_table(args):
    """Generate single RANK_TABLE config file"""
    # visible_devices
    visible_devices = args.visible_devices.split(',')

    # server_id
    ip = get_host_ip()
    server_id = args.server_ip if args.server_ip else ip
    if not server_id:
        raise ValueError("Please input server ip!")

    # device_num
    first_num = int(args.device_num.split('[')[1].split(',')[0])
    last_num = int(args.device_num.split(')')[0].split(',')[-1])
    if first_num > last_num:
        raise ValueError(f"First num {first_num} of device num {args.device_num} must less than last num {last_num}!")
    device_num_list = list(range(first_num, last_num))

    assert len(visible_devices) >= len(device_num_list)

    # construct rank_table
    device_ips: Dict[Any, Any] = {}
    try:
        for device_id in device_num_list:
            ret = os.popen(f"hccn_tool -i {device_id} -ip -g").readlines()
            device_ips[str(device_id)] = ret[0].split(":")[1].replace('\n', '')
    except IndexError:
        try:
            with open('/etc/hccn.conf', 'r') as fin:
                for hccn_item in fin.readlines():
                    if hccn_item.strip().startswith('address_'):
                        device_id, device_ip = hccn_item.split('=')
                        device_id = device_id.split('_')[1]
                        device_ips[device_id] = device_ip.strip()
        except OSError:
            raise SystemError("Failed to find information for rank_table")

    rank_table = {
        'version': '1.0',
        'status': 'completed',
        'group_id': '0',
        'serve_count': "1",
        'server_list': []
    }

    device_list = []
    rank_id = 0
    for instance_id in range(len(device_num_list)):
        device_id = visible_devices[instance_id]
        device_ip = device_ips[device_id]
        device = {
            'device_id': device_id,
            'device_ip': device_ip,
            'rank_id': str(rank_id)
        }
        rank_id += 1
        device_list.append(device)

    global_instance_rank = args.num_instances + args.instance_rank
    rank_table['server_list'].append({
        'server_id': f"server-{global_instance_rank}",
        'server_ip': server_id,
        'device': device_list,
    })

    # Save rank_table to file
    table_fn = os.path.join(args.output_dir,
                           f'{args.instance_role}_{args.instance_rank}_rank_table_{len(device_num_list)}u.json')
    with open(table_fn, 'w') as table_fp:
        json.dump(rank_table, table_fp, indent=4)
    print(f"Completed: rank_table file was saved in: {table_fn}")

def merge_rank_table(args):
    """Merge multiple RANK_TABLE config files"""
    prefill_jsons = []
    decode_jsons = []

    for f_name in args.file_list:
        with open(f_name) as f:
            f_json = json.load(f)
            if "prefill" in f_name:
                prefill_jsons.append(f_json)
            elif "decode" in f_name:
                decode_jsons.append(f_json)

    rank_table = {
        'version': '1.0',
        'status': "completed",
        'server_group_list': [
            {
                "group_id": "0",
                "server_count": "1",
                "server_list": [{
                    "server_id": "router",
                    "server_ip": "127.0.0.1"
                }]
            }
        ]
    }

    if prefill_jsons:
        rank_table['server_group_list'].append({
            "group_id": "1",
            "server_count": str(len(prefill_jsons)),
            "server_list": [s for j in prefill_jsons for s in j['server_list']]
        })

    if decode_jsons:
        rank_table['server_group_list'].append({
            "group_id": "2",
            "server_count": str(len(decode_jsons)),
            "server_list": [s for j in decode_jsons for s in j['server_list']]
        })

    rank_id = 0
    server_id_counter = 0

    for group in rank_table['server_group_list']:
        if group['group_id'] == "0":
            continue

        local_rank_id = 0
        for server in group['server_list']:
            server['server_id'] = f"server-{server_id_counter}"
            server_id_counter += 1
            local_rank_id = 0
            for device in server['device']:
                device['rank_id'] = str(local_rank_id)
                local_rank_id += 1
                rank_id += 1

    table_name = os.path.join(args.output_dir, f'global_ranktable.json')
    with open(table_name, 'w') as table_fp:
        json.dump(rank_table, table_fp, indent=4)
    print(f"Completed: rank_table file was saved in: {table_name}")

def main():
    args = parse_args()
    if args.command == 'generate':
        generate_rank_table(args)
    elif args.command == 'merge':
        merge_rank_table(args)

if __name__ == "__main__":
    main()