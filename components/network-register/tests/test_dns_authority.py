import unittest
from types import SimpleNamespace
import dns.flags
import dns.message
import dns.name
import dns.rcode
import dns.resolver
import dns.rrset
from zog.network_register.contracts import NetworkError
from zog.network_register.dns_authority import DnsAuthorityCollector
from zog.network_register.evidence import EvidenceGate
from zog.network_register.models import Connection, ZoneBinding


def rr(name, kind, *values):
    return dns.rrset.from_text(name, 300, 'IN', kind, *values)


def soa(zone):
    return rr(zone, 'SOA', 'ns1.example.net. hostmaster.example.net. 1 60 60 60 60')


class Answer:
    def __init__(self, rows):
        self.rrset = rows
        self.canonical_name = rows.name
    def __iter__(self): return iter(self.rrset)


class Wire:
    def __init__(self):
        self.calls = []; self.resolutions = []; self.edit = lambda q, r, address: r
        self.parent_names = ('parent.example.net.',)
        self.ip = {'parent.example.net.':'1.1.1.1','ns1.example.net.':'8.8.8.8','ns2.example.net.':'8.8.4.4'}
    def resolve(self, name, kind, **kwargs):
        self.resolutions.append((str(name),kind,kwargs))
        if kind == 'NS':
            if str(name) != 'uk.': raise dns.resolver.NoAnswer()
            return Answer(rr('uk.', 'NS', *self.parent_names))
        if kind == 'AAAA': raise dns.resolver.NoAnswer()
        return Answer(rr(str(name), 'A', self.ip[str(name)]))
    def query(self, q, address, timeout):
        self.calls.append((q,address,timeout))
        name, kind = q.question[0].name, q.question[0].rdtype
        r = dns.message.make_response(q)
        r.flags |= dns.flags.AA
        if kind == dns.rdatatype.SOA:
            r.answer.append(soa(str(name)))
        elif address == '1.1.1.1':
            r.flags &= ~dns.flags.AA
            r.authority.append(rr('example.uk.', 'NS', 'ns1.example.net.', 'ns2.example.net.'))
        else:
            r.authority.append(soa('example.uk.'))
        r = self.edit(q,r,address)
        return dns.message.from_wire(r.to_wire())  # exercise the real message parser


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.w = Wire()
        self.c = Connection('c','owner','cloudflare','account','ref',status='ready')
        self.b = ZoneBinding('b','owner','c','zone','example.uk','hosts.example.uk',status='ready',
                             nameservers=('ns1.example.net','ns2.example.net'))
        self.collector = DnsAuthorityCollector(self.w,query=self.w.query,clock=lambda:1000)
    def collect(self): return self.collector.authority(self.c,self.b)
    def edit(self, callback): self.w.edit = callback
    def fails(self):
        with self.assertRaises(NetworkError): self.collect()
    def test_direct_parent_and_every_authoritative_server(self):
        evidence = self.collect()
        self.assertEqual(len(evidence.answers),2)
        EvidenceGate(SimpleNamespace(authority=lambda *_:evidence),clock=lambda:1001).authority(self.c,self.b)
        self.assertEqual(len(self.w.calls),6)
        self.assertTrue(all(not q.flags & dns.flags.RD for q,_,_ in self.w.calls))
        self.assertTrue(all(not opts['search'] for _,_,opts in self.w.resolutions))
    def test_parent_delegation_mismatch(self):
        def edit(q,r,a):
            if a=='1.1.1.1' and q.question[0].rdtype==dns.rdatatype.NS:
                r.authority[:]=[rr('example.uk.','NS','other.example.net.')]
            return r
        self.edit(edit);self.fails()
    def test_child_answer_does_not_prove_parent_delegation(self):
        def edit(q,r,a):
            if a=='1.1.1.1' and q.question[0].rdtype==dns.rdatatype.NS:
                r.answer[:]=r.authority;r.authority.clear();r.flags|=dns.flags.AA
            return r
        self.edit(edit);self.fails()
    def test_lame_server(self):
        self.edit(lambda q,r,a: self.flags(r, r.flags & ~dns.flags.AA) if a=='8.8.4.4' else r);self.fails()
    @staticmethod
    def flags(r, flags): r.flags=flags;return r
    def test_wrong_soa_zone(self):
        def edit(q,r,a):
            if a=='8.8.4.4' and q.question[0].rdtype==dns.rdatatype.SOA:r.answer[:]=[soa('other.uk.')]
            return r
        self.edit(edit);self.fails()
    def test_subdelegation_referral(self):
        def edit(q,r,a):
            if str(q.question[0].name)=='hosts.example.uk.':
                r.flags&=~dns.flags.AA;r.authority[:]=[rr('hosts.example.uk.','NS','other.example.net.')]
            return r
        self.edit(edit);self.fails()
    def test_prefix_aliases_rejected(self):
        for kind in ('CNAME','DNAME'):
            with self.subTest(kind=kind):
                def edit(q,r,a):
                    if str(q.question[0].name)=='hosts.example.uk.':r.answer[:]=[rr('hosts.example.uk.',kind,'other.example.net.')]
                    return r
                self.edit(edit);self.fails()
    def test_nxdomain_with_correct_soa_is_unshadowed(self):
        def edit(q,r,a):
            if str(q.question[0].name)=='hosts.example.uk.':r.set_rcode(dns.rcode.NXDOMAIN)
            return r
        self.edit(edit);self.collect()
    def test_negative_without_soa_fails(self):
        def edit(q,r,a):
            if str(q.question[0].name)=='hosts.example.uk.':r.authority.clear()
            return r
        self.edit(edit);self.fails()
    def test_malformed_response_question_or_id(self):
        def edit(q,r,a):r.id ^= 1;return r
        self.edit(edit);self.fails()
    def test_truncated_tcp_response(self):
        self.edit(lambda q,r,a:self.flags(r,r.flags|dns.flags.TC));self.fails()
    def test_servfail_is_transient(self):
        def edit(q,r,a):r.set_rcode(dns.rcode.SERVFAIL);return r
        self.edit(edit)
        with self.assertRaises(NetworkError) as caught:self.collect()
        self.assertEqual(caught.exception.code,'transient')
    def test_private_server_address_never_queried(self):
        self.w.ip['parent.example.net.']='127.0.0.1';self.fails();self.assertFalse(self.w.calls)
    def test_multicast_address_rejected(self):
        self.w.ip['parent.example.net.']='224.0.0.1';self.fails();self.assertFalse(self.w.calls)
    def test_missing_address_fails(self):
        self.w.resolve=lambda *a,**k: (_ for _ in ()).throw(dns.resolver.NoAnswer())
        self.fails()
    def test_query_budget(self):
        self.collector.max_queries=1;self.fails();self.assertFalse(self.w.calls)
    def test_deadline(self):
        ticks=iter([0,46]);self.collector.monotonic=lambda:next(ticks)
        self.fails();self.assertFalse(self.w.calls)
    def test_timeout_sanitized(self):
        self.collector.query=lambda *a,**k: (_ for _ in ()).throw(OSError('private material'))
        with self.assertRaises(NetworkError) as caught:self.collect()
        self.assertNotIn('private material',str(caught.exception))
    def test_climbs_non_zone_parent_and_checks_each_prefix_ancestor(self):
        from dataclasses import replace
        self.b=replace(self.b,zone_name='sub.example.uk',prefix='hosts.team.sub.example.uk')
        def edit(q,r,a):
            if a=='1.1.1.1' and q.question[0].rdtype==dns.rdatatype.NS:
                r.authority[:]=[rr('sub.example.uk.','NS','ns1.example.net.','ns2.example.net.')]
            elif q.question[0].rdtype==dns.rdatatype.NS:r.authority[:]=[soa('sub.example.uk.')]
            return r
        self.edit(edit);self.collect()
        queried=[str(q.question[0].name) for q,_,_ in self.w.calls]
        self.assertIn('team.sub.example.uk.',queried);self.assertIn('hosts.team.sub.example.uk.',queried)
    def test_bad_owner_fails_before_network(self):
        from dataclasses import replace
        self.b=replace(self.b,owner_id='other');self.fails();self.assertFalse(self.w.resolutions)
    def test_missing_pins_fail_before_network(self):
        from dataclasses import replace
        self.b=replace(self.b,nameservers=());self.fails();self.assertFalse(self.w.resolutions)

    def test_disagreeing_second_parent_blocks(self):
        self.w.parent_names=('parent.example.net.','parent2.example.net.')
        self.w.ip['parent2.example.net.']='9.9.9.9'
        def edit(q,r,a):
            if a=='9.9.9.9' and q.question[0].rdtype==dns.rdatatype.NS:
                r.flags&=~dns.flags.AA;r.authority[:]=[rr('example.uk.','NS','other.example.net.')]
            return r
        self.edit(edit);self.fails()
    def test_ns_address_alias_rejected(self):
        original=self.w.resolve
        def resolve(name,kind,**kwargs):
            answer=original(name,kind,**kwargs)
            if kind=='A':answer.canonical_name=dns.name.from_text('alias.example.net.')
            return answer
        self.w.resolve=resolve;self.fails();self.assertFalse(self.w.calls)
    def test_alternate_address_after_timeout(self):
        original=self.w.resolve
        def resolve(name,kind,**kwargs):
            if str(name)=='parent.example.net.' and kind=='A':
                return Answer(rr(str(name),'A','1.0.0.1','1.1.1.1'))
            return original(name,kind,**kwargs)
        self.w.resolve=resolve
        query=self.collector.query
        def fallback(q,address,**kwargs):
            if address=='1.0.0.1':raise dns.exception.Timeout()
            return query(q,address,**kwargs)
        self.collector.query=fallback;self.collect()

if __name__=='__main__':unittest.main()

class DelegationOnlyTests(unittest.TestCase):
    setUp = CollectorTests.setUp
    edit = CollectorTests.edit
    collect = CollectorTests.collect
    fails = CollectorTests.fails
    def test_parent_only_does_not_require_child_soa(self):
        def refuse(q,r,address):
            if address!='1.1.1.1':r.set_rcode(dns.rcode.REFUSED)
            return r
        self.edit(refuse)
        self.assertEqual(self.collector.delegation(self.c,self.b),1000)
        self.assertTrue(all(address=='1.1.1.1' for _,address,_ in self.w.calls))
        self.fails()
    def test_parent_only_rejects_foreign_referral(self):
        def foreign(q,r,address):
            if q.question[0].rdtype==dns.rdatatype.NS:
                r.authority[:]=[rr('example.uk.','NS','foreign.example.net.')]
            return r
        self.edit(foreign)
        with self.assertRaises(NetworkError):self.collector.delegation(self.c,self.b)
