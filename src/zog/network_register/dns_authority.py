"""Bounded, read-only DNS authority collection using dnspython.

Recursive DNS is used only to bootstrap parent servers and server addresses.
Delegation and SOA/prefix evidence come from direct, nonrecursive TCP queries.
No provider credential is used here. This is not DNSSEC validation.
"""
import ipaddress
import time
import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdatatype
import dns.resolver
from .contracts import NetworkError
from .evidence import AuthorityEvidence, AuthoritativeAnswer


class DnsAuthorityCollector:
    def __init__(self, resolver=None, *, query=dns.query.tcp, clock=time.time,
                 monotonic=time.monotonic, timeout=3.0, lifetime=45.0, max_queries=128):
        if not 0 < timeout <= 10 or not 0 < lifetime <= 60 or not 1 <= max_queries <= 256:
            raise ValueError('Invalid DNS collection limits')
        self.resolver = resolver if resolver is not None else dns.resolver.Resolver()
        self.query, self.clock, self.monotonic = query, clock, monotonic
        self.timeout, self.lifetime, self.max_queries = timeout, lifetime, max_queries

    def authority(self, connection, binding):
        if connection.id != binding.connection_id or connection.owner_id != binding.owner_id or not binding.nameservers:
            raise NetworkError('permission')
        run = _Collection(self)
        try:
            return run.collect(connection, binding)
        except NetworkError:
            raise
        except (dns.exception.DNSException, OSError):
            raise NetworkError('transient') from None
        except (ValueError, TypeError, AttributeError, KeyError):
            raise NetworkError('validation') from None


    def delegation(self, connection, binding):
        """Parent-only observation for explicit first-record initialization.

        This is NOT authoritative-zone evidence and cannot activate a binding.
        """
        if connection.id != binding.connection_id or connection.owner_id != binding.owner_id or not binding.nameservers:
            raise NetworkError('permission')
        try:
            return _Collection(self).delegation(binding)
        except NetworkError:
            raise
        except (dns.exception.DNSException, OSError):
            raise NetworkError('transient') from None
        except (ValueError, TypeError, AttributeError, KeyError):
            raise NetworkError('validation') from None


class _Collection:
    def __init__(self, collector):
        self.c = collector
        self.deadline = collector.monotonic() + collector.lifetime
        self.remaining = collector.max_queries
        self.address_cache = {}

    def budget(self):
        left = self.deadline - self.c.monotonic()
        if left <= 0 or self.remaining <= 0:
            raise NetworkError('transient')
        self.remaining -= 1
        return min(left, self.c.timeout)

    def resolve(self, name, kind):
        return self.c.resolver.resolve(name, kind, search=False, lifetime=self.budget())

    @staticmethod
    def names(rrset):
        names = tuple(sorted(str(r.target).rstrip('.').lower() for r in rrset))
        if not 1 <= len(names) <= 16 or len(set(names)) != len(names):
            raise NetworkError('validation')
        return names

    def parent(self, zone):
        name = zone.parent()
        for _ in range(127):
            try:
                answer = self.resolve(name, 'NS')
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                if name == dns.name.root: break
                name = name.parent()
                continue
            if answer.canonical_name != name or answer.rrset.name != name or answer.rrset.rdtype != dns.rdatatype.NS:
                raise NetworkError('conflict')
            return name, self.names(answer.rrset)
        raise NetworkError('conflict')

    def addresses(self, server):
        if server in self.address_cache:
            return self.address_cache[server]
        addresses = []
        name = dns.name.from_text(server)
        for kind in ('A', 'AAAA'):
            try: answer = self.resolve(name, kind)
            except dns.resolver.NoAnswer: continue
            if answer.canonical_name != name or answer.rrset.name != name:
                raise NetworkError('conflict')
            for row in answer:
                address = ipaddress.ip_address(row.address)
                if not address.is_global or address.is_multicast:
                    raise NetworkError('permission')
                addresses.append(str(address))
        if not addresses or len(addresses) > 8:
            raise NetworkError('validation')
        result = tuple(dict.fromkeys(addresses))
        self.address_cache[server] = result
        return result

    def ask(self, server, name, kind):
        request = dns.message.make_query(name, kind)
        request.flags &= ~dns.flags.RD
        for address in self.addresses(server):
            try:
                reply = self.c.query(request, address, timeout=self.budget())
            except (dns.exception.Timeout, OSError):
                continue  # alternate address, never alternate contradictory evidence
            if not request.is_response(reply) or reply.flags & dns.flags.TC:
                raise NetworkError('validation')
            if reply.rcode() not in (dns.rcode.NOERROR, dns.rcode.NXDOMAIN):
                raise NetworkError('transient')
            if any(r.rdtype in (dns.rdatatype.CNAME, dns.rdatatype.DNAME) for r in reply.answer + reply.authority):
                raise NetworkError('conflict')
            return reply
        raise NetworkError('transient')

    @staticmethod
    def soa(reply, zone, *, apex=False):
        if not reply.flags & dns.flags.AA:
            raise NetworkError('conflict')
        if apex:
            if reply.rcode() != dns.rcode.NOERROR:
                raise NetworkError('conflict')
            rows = reply.answer
        else:
            # NS NODATA/NXDOMAIN must carry the bound zone's authoritative SOA.
            if reply.answer or any(r.rdtype == dns.rdatatype.NS for r in reply.authority):
                raise NetworkError('conflict')
            rows = reply.authority
        soa = [r for r in rows if r.rdtype == dns.rdatatype.SOA]
        if len(soa) != 1 or soa[0].name != zone or len(soa[0]) != 1:
            raise NetworkError('conflict')

    def delegation(self, binding):
        zone = dns.name.from_text(binding.zone_name)
        parent, parents = self.parent(zone)
        delegation_started = self.c.clock()
        for server in parents:
            self.soa(self.ask(server, parent, 'SOA'), parent, apex=True)
            reply = self.ask(server, zone, 'NS')
            # Require a parent referral, not a child-apex NS answer from a server
            # hosting both zones. Ambiguous parent/child hosting fails closed.
            refs = [r for r in reply.authority if r.rdtype == dns.rdatatype.NS]
            if (reply.rcode() != dns.rcode.NOERROR or reply.answer or reply.flags & dns.flags.AA
                    or len(refs) != 1 or refs[0].name != zone
                    or self.names(refs[0]) != binding.nameservers):
                raise NetworkError('conflict')
        if self.c.monotonic() > self.deadline: raise NetworkError('transient')
        return delegation_started

    def collect(self, connection, binding):
        delegation_started = self.delegation(binding)
        zone = dns.name.from_text(binding.zone_name)
        checks = []
        name = dns.name.from_text(binding.prefix)
        while name != zone:
            if not name.is_subdomain(zone): raise NetworkError('validation')
            checks.append(name)
            name = name.parent()
        answers = []
        for server in binding.nameservers:
            observed = self.c.clock()  # conservative: never refresh a previous response timestamp
            self.soa(self.ask(server, zone, 'SOA'), zone, apex=True)
            for name in reversed(checks):
                self.soa(self.ask(server, name, 'NS'), zone)
            answers.append(AuthoritativeAnswer(server, binding.zone_name, True, observed, True))
        if self.c.monotonic() > self.deadline: raise NetworkError('transient')
        return AuthorityEvidence(connection.owner_id, connection.id, connection.revision, connection.credential_ref,
            binding.id, binding.revision, binding.zone_id, binding.zone_name, binding.prefix,
            binding.nameservers, delegation_started, tuple(answers))
