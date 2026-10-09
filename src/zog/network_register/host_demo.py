"""Optional host-deploy adapter; AWS credentials use boto3's normal provider chain."""
import argparse
import json
import shlex
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description='Provision or inspect the DNS test host with host-deploy')
    p.add_argument('--workspace', required=True)
    sub=p.add_subparsers(dest='action', required=True)
    q=sub.add_parser('provision')
    q.add_argument('--specification', required=True)
    q.add_argument('--name', default='network-register-demo')
    q.add_argument('--region', default='us-east-1')
    q.add_argument('--profile')
    q=sub.add_parser('verify-dns'); q.add_argument('name'); q.add_argument('expected_address')
    sub.add_parser('status')
    sub.add_parser('stop')
    a=p.parse_args()
    from zog.host_deploy.workspace import initialize, save
    from zog.host_deploy.provision import provision, configuration, Cloud, operate
    from zog.host_deploy.runner import Host
    if a.action == 'provision':
        initialize(a.workspace,a.name,a.profile,a.region)
        config=provision(a.workspace,json.loads(Path(a.specification).read_text()),discovery=False)
        Host(config).online()
    else:
        _,config=configuration(a.workspace)
    if a.action == 'stop':
        print(json.dumps(operate(a.workspace,'stop'),indent=2))
        return
    instance=Cloud(config).owned(config['instance_id'],config['account_id'])
    if a.action == 'verify-dns':
        from .operations import domain_name
        import ipaddress
        name=domain_name(a.name)
        expected=str(ipaddress.IPv4Address(a.expected_address))
        code=('import socket,json; name='+repr(name)+'; expected='+repr(expected)+'; '
              'addresses=sorted({r[4][0] for r in socket.getaddrinfo(name,80,family=socket.AF_INET,type=socket.SOCK_STREAM)}); '
              'print(json.dumps({"name":name,"expected":expected,"addresses":addresses,"matched":addresses==[expected]})); '
              'assert addresses==[expected], "DNS address does not match"')
        output=Host(config).command('python3 -c '+shlex.quote(code))
        result=json.loads(output)
        save(Path(a.workspace)/'dns-verification.json',result)
    else:
        result={k:instance.get(k) for k in ['InstanceId','State','PublicIpAddress']}
    print(json.dumps(result,indent=2))


if __name__ == '__main__': main()
