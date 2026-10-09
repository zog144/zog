import ipaddress
import json
import re
from decimal import Decimal
from .state import locked, save


def domain_name(value):
    value = value.rstrip('.').encode('idna').decode().lower()
    if len(value) > 253 or '.' not in value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in value.split('.')):
        raise ValueError('Invalid domain name')
    return value


def register(client, domain, maximum_usd, directory, registrant_type=None):
    domain = domain_name(domain)
    body = {'domain_name': domain, 'auto_renew': False}
    if registrant_type is not None:
        if registrant_type not in ('IND', 'FIND') or not domain.endswith('.uk'):
            raise ValueError('Individual registrant type requires a .uk domain and IND or FIND')
        body['contact_extensions'] = {'registrant_type': registrant_type}
    maximum = Decimal(str(maximum_usd))
    if not maximum.is_finite() or maximum <= 0:
        raise ValueError('Maximum price must be positive and finite')
    with locked(directory) as root:
        path = root / ('registration-' + domain + '.json')
        if path.exists():
            previous = json.loads(path.read_text())
            if previous['account_id'] != client.account:
                raise ValueError('Registration belongs to a different account')
            raise RuntimeError('Registration already attempted; use registration-status. Never automatically resubmit.')
        rows = client.check([domain])['domains']
        if len(rows) != 1 or rows[0]['name'] != domain:
            raise ValueError('Check response does not match requested domain')
        quote = rows[0]
        if quote.get('registrable') is not True or quote.get('tier') != 'standard':
            raise ValueError('Domain is unavailable, unsupported, or not standard priced')
        pricing = quote['pricing']
        price = Decimal(pricing['registration_cost'])
        if pricing['currency'] != 'USD' or not price.is_finite() or price <= 0 or price > maximum:
            raise ValueError('Current registration price exceeds permitted USD budget')
        record = {'schema': 1, 'account_id': client.account, 'domain': domain,
                  'quote': quote, 'maximum_usd': str(maximum), 'phase': 'submission-uncertain', 'request': body}
        save(path, record)
        # This marker survives timeout, process exit, and response-save failure.
        try:
            result = client.result('POST', client.registrar + '/registrations',
                                   body)
        except Exception as error:
            record['last_error'] = str(error)
            save(path, record)
            raise
        record.update(phase='response-recorded', result=result)
        save(path, record)
        return result


def registration_status(client, domain, directory):
    domain = domain_name(domain)
    result = client.result('GET', client.registrar + '/registrations/' + domain + '/registration-status')
    with locked(directory) as root:
        path = root / ('registration-' + domain + '.json')
        if path.exists():
            record = json.loads(path.read_text())
            if record['account_id'] != client.account:
                raise ValueError('Registration belongs to a different account')
            record.update(last_status=result)
            save(path, record)
    return result


def zone_for(client, domain):
    domain = domain_name(domain)
    zones = list(client.pages('/zones', {'name': domain, 'account.id': client.account}))
    zones = [z for z in zones if z['name'] == domain and z['account']['id'] == client.account]
    if len(zones) != 1:
        raise ValueError('Expected exactly one zone in this account; registration may still be provisioning')
    return zones[0]


def ensure_a(client, domain, name, address, directory):
    domain, name = domain_name(domain), domain_name(name)
    if not name.endswith('.' + domain):
        raise ValueError('Record must be a subdomain of the selected zone')
    address = str(ipaddress.IPv4Address(address))
    with locked(directory) as root:
        zone = zone_for(client, domain)
        path = '/zones/' + zone['id'] + '/dns_records'
        marker = 'Managed by Zog network-register: ' + name
        records = list(client.pages(path, {'name': name}))
        if len(records) > 1:
            raise ValueError('Multiple records at this name; refusing to overwrite')
        body = {'type': 'A', 'name': name, 'content': address, 'ttl': 60, 'proxied': False, 'comment': marker}
        if records:
            current = records[0]
            if current['type'] != 'A' or current.get('comment') != marker:
                raise ValueError('Existing record is not owned by network-register')
            if all(current.get(k) == v for k, v in body.items()):
                result = current
            else:
                result = client.result('PATCH', path + '/' + current['id'], body)
        else:
            # An uncertain create is reconciled by listing the exact name on the next run.
            result = client.result('POST', path, body)
        save(root / ('dns-' + name + '.json'), {'account_id': client.account, 'zone_id': zone['id'], 'record': result})
        return result


def ensure_zone(client, domain):
    """Create a DNS zone only. This does not register or purchase the domain."""
    domain = domain_name(domain)
    zones = list(client.pages('/zones', {'name': domain, 'account.id': client.account}))
    if zones:
        return zone_for(client, domain)
    return client.result('POST', '/zones', {'account': {'id': client.account}, 'name': domain, 'type': 'full'})
