import argparse
import json
import sys
from .client import Client, credentials
from .dns import DnsRecords
from .operations import register, registration_status, ensure_a, domain_name, zone_for, ensure_zone


def main():
    p = argparse.ArgumentParser(description='Zog Cloudflare registration and DNS')
    p.add_argument('--token-file', help='File with Account ID: and API token: labels; never bundled')
    p.add_argument('--state', default='state')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('verify')
    sub.add_parser('porkbun-verify')
    q = sub.add_parser('porkbun-domains'); q.add_argument('--start', type=int, default=0)
    q = sub.add_parser('porkbun-records'); q.add_argument('domain')
    sub.add_parser('zones')
    q = sub.add_parser('zone-ensure'); q.add_argument('domain')
    q = sub.add_parser('search'); q.add_argument('term')
    q = sub.add_parser('check'); q.add_argument('domains', nargs='+')
    q = sub.add_parser('register'); q.add_argument('domain'); q.add_argument('--maximum-usd', required=True)
    q.add_argument('--registrant-type', choices=['IND', 'FIND'], help='UK individual (IND) or non-UK individual (FIND); .uk only')
    q = sub.add_parser('registration-status'); q.add_argument('domain')
    q = sub.add_parser('dns-show'); q.add_argument('domain'); q.add_argument('name')
    q = sub.add_parser('dns-set'); q.add_argument('domain'); q.add_argument('name'); q.add_argument('address')
    q = sub.add_parser('a-set'); q.add_argument('domain'); q.add_argument('name'); q.add_argument('address'); q.add_argument('--owner-id', required=True); q.add_argument('--ttl', type=int, default=60)
    q = sub.add_parser('a-remove'); q.add_argument('domain'); q.add_argument('name'); q.add_argument('--owner-id', required=True)
    a = p.parse_args()
    try:
        if a.command.startswith('porkbun-'):
            from .porkbun import PorkbunClient, credentials as porkbun_credentials
            porkbun = PorkbunClient(*porkbun_credentials(a.token_file))
            if a.command == 'porkbun-verify': result = porkbun.verify()
            elif a.command == 'porkbun-domains': result = porkbun.list_domains(a.start)
            else: result = porkbun.records(a.domain)
            print(json.dumps(result, indent=2))
            return 0
        c = Client(*credentials(a.token_file))
        if a.command == 'verify': result = c.result('GET', '/accounts/' + c.account + '/tokens/verify')
        elif a.command == 'zones': result = list(c.pages('/zones', {'account.id': c.account}))
        elif a.command == 'zone-ensure': result = ensure_zone(c, a.domain)
        elif a.command == 'search': result = c.search(a.term)
        elif a.command == 'check': result = c.check([domain_name(d) for d in a.domains])
        elif a.command == 'register': result = register(c, a.domain, a.maximum_usd, a.state, a.registrant_type)
        elif a.command == 'registration-status': result = registration_status(c, a.domain, a.state)
        elif a.command == 'dns-set': result = ensure_a(c, a.domain, a.name, a.address, a.state)
        elif a.command == 'a-set': result = DnsRecords(c, a.domain, a.state).ensure_a(a.name, a.address, a.owner_id, a.ttl)
        elif a.command == 'a-remove': result = DnsRecords(c, a.domain, a.state).remove_a(a.name, a.owner_id)
        else:
            zone = zone_for(c, a.domain)
            result = list(c.pages('/zones/' + zone['id'] + '/dns_records', {'name': domain_name(a.name)}))
        print(json.dumps(result, indent=2))
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0
