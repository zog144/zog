"""Single-controller, durable, owner-bound Cloudflare A-record reconciliation."""
import hashlib
import ipaddress
import json
from .operations import domain_name, zone_for
from .state import locked, save


class DnsConflict(RuntimeError):
    """An assignment or provider record conflicts with the requested owner."""


class DnsRecords:
    def __init__(self, client, domain, directory):
        self.client = client
        self.domain = domain_name(domain)
        self.directory = directory

    def _name(self, name):
        name = domain_name(name)
        if not name.endswith('.' + self.domain):
            raise ValueError('Expected a subdomain of the configured domain')
        return name

    def inspect(self, name):
        name = self._name(name)
        zone = zone_for(self.client, self.domain)
        return list(self.client.pages('/zones/' + zone['id'] + '/dns_records', {'name': name}))

    def ensure_a(self, name, address, owner_id, ttl=60):
        address = str(ipaddress.IPv4Address(address))
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 60 <= ttl <= 86400:
            raise ValueError('TTL must be an integer from 60 to 86400 seconds')
        return self._reconcile(name, owner_id, address, ttl)

    def remove_a(self, name, owner_id):
        return self._reconcile(name, owner_id, None, None)

    def _reconcile(self, name, owner_id, address, ttl):
        name = self._name(name)
        if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 256:
            raise ValueError('Supply a stable, nonempty owner ID of at most 256 characters')
        with locked(self.directory) as root:
            path = root / ('assignment-' + name + '.json')
            binding = json.loads(path.read_text()) if path.exists() else None
            if binding and (binding['account_id'], binding['domain'], binding['owner_id']) != (self.client.account, self.domain, owner_id):
                raise DnsConflict('Name is reserved to a different account, domain or owner')
            zone = zone_for(self.client, self.domain)
            if binding and binding['zone_id'] != zone['id']:
                raise DnsConflict('Zone identity changed')
            endpoint = '/zones/' + zone['id'] + '/dns_records'
            rows = list(self.client.pages(endpoint, {'name': name}))
            if len(rows) > 1 or any(r['name'].rstrip('.').lower() != name for r in rows):
                raise DnsConflict('Ambiguous or mismatched DNS records')
            current = rows[0] if rows else None
            marker = 'Zog network-register owner ' + hashlib.sha256(json.dumps([self.client.account, zone['id'], name, owner_id]).encode()).hexdigest()
            if current:
                if not binding or current['type'] != 'A' or current.get('comment') != marker:
                    raise DnsConflict('Existing record is not owned by this assignment')
                if binding.get('record_id') and binding['record_id'] != current['id']:
                    raise DnsConflict('Provider record identity changed')
                if not binding.get('record_id') and binding.get('phase') != 'applying':
                    raise DnsConflict('Unexpected record for absent assignment')
            if not binding:
                binding = {'schema': 1, 'account_id': self.client.account, 'domain': self.domain,
                           'zone_id': zone['id'], 'name': name, 'owner_id': owner_id, 'record_id': None}
            if address is None:
                action = 'deleted' if current else 'absent'
                body = None
            else:
                body = {'type': 'A', 'name': name, 'content': address, 'ttl': ttl, 'proxied': False, 'comment': marker}
                action = 'created' if not current else ('unchanged' if all(current.get(k) == v for k,v in body.items()) else 'updated')
            # Save intent and reservation before any remote mutation. Retry lists the
            # exact name and reconciles even after response loss or a failed save.
            binding.update(phase='applying', desired=body)
            if not current:
                binding['record_id'] = None
            save(path, binding)
            result = current
            if action == 'created':
                result = self.client.result('POST', endpoint, body)
            elif action == 'updated':
                result = self.client.result('PATCH', endpoint + '/' + current['id'], body)
            elif action == 'deleted':
                self.client.result('DELETE', endpoint + '/' + current['id'])
                result = None
            if address is None:
                result = None
            binding.update(phase='absent' if result is None else 'present', record_id=result['id'] if result else None, record=result)
            save(path, binding)
            return {'action': action, 'name': name, 'owner_id': owner_id, 'zone_id': zone['id'], 'record': result}
