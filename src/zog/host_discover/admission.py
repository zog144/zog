"""Fresh root-authenticated ledger observation and experimental anchored journal."""
import fcntl
import os
from zog.host_install import state_admission
from zog.host_install.state_contract import canonical, decode, header, require, StateError
from zog.host_install.state_inspect import metadata, read_at

SCHEMA = 1  # This module's journal only; not a controller schema declaration.


def observe(context):
    """Never accept projection files, cached reports or caller-supplied evidence."""
    try:
        result=state_admission.request_live(context)
        require(result['recovery_hold'] is False and result['identity_action']=='verify-existing' and
                result['receipt'] is not None,'recovery-required','Protected hold or missing receipt')
        return result
    except StateError:
        raise
    except (OSError,ValueError,TypeError,KeyError) as exc:
        raise StateError('admission-unavailable','Fresh protected observation unavailable') from exc


def verify_existing(state):
    """One admission attempt: probe precedes this, two fresh reads bracket load."""
    try:
        state.check()
        before=observe(state.context)
        state._identity(before['receipt'])  # descriptor anchored; never prepare
        state.check()
        after=observe(state.context)
        require(before['receipt']==after['receipt'] and before['bindings']==after['bindings'],
                'admission-changed','Protected evidence changed during identity validation')
        state.check()
        return after
    except Exception as exc:
        state.fail(getattr(exc,'code','identity-state-invalid'))


class Journal:
    """One locked, bounded transaction record; explicit preparation only.

    Successful writes are fsynced before effects. An interrupted write leaves a
    blocking pending marker. No startup repair, reset or migration is implicit.
    """
    def __init__(self,context):
        self.context=context;self.fd=None;self.lock=None
        home=os.open('host-discover',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=context.fd)
        try:
            metadata(home,970,970,0o700)
            self.fd=os.open('control',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=home)
            metadata(self.fd,970,970,0o700)
            require(os.fstat(self.fd).st_dev==os.fstat(context.fd).st_dev,'nested-mount','control')
        except BaseException:
            self.close();raise
        finally:os.close(home)

    def recheck(self):
        self.context.recheck()
        home=os.open('host-discover',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=self.context.fd)
        child=None
        try:
            metadata(home,970,970,0o700)
            child=os.open('control',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=home)
            metadata(child,970,970,0o700)
            a,b=os.fstat(child),os.fstat(self.fd)
            require((a.st_dev,a.st_ino)==(b.st_dev,b.st_ino),'managed-directory-changed','Control directory replaced')
        finally:
            if child is not None:os.close(child)
            os.close(home)

    def acquire(self,prepare=False):
        flags=os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK
        if prepare:flags|=os.O_CREAT|os.O_EXCL
        self.lock=os.open('managed.lock',flags,0o600,dir_fd=self.fd)
        metadata(self.lock,970,970,0o600,False)
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise StateError('managed-busy','Another process owns admission') from None
        self.context.recheck()

    def read(self):
        self.recheck()
        require('managed.pending' not in os.listdir(self.fd),'managed-journal-incomplete','Explicit recovery required')
        value=decode(read_at(self.fd,'managed.json',970,970,0o600))
        header(value,'zog-managed-journal','installation_id state_volume_id fingerprint registries replay')
        require(type(value['registries']) is dict and len(value['registries'])<=32 and type(value['replay']) is list and len(value['replay'])<=128,'managed-journal-schema','Invalid bounded state')
        from .beacon_state import validate
        return validate(value)

    def write(self,value):
        self.recheck()
        from .beacon_state import validate
        validate(value)
        raw=canonical(value);require(len(raw)<=65536,'managed-journal-capacity','Journal full')
        fd=os.open('managed.pending',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=self.fd)
        try:
            view=memoryview(raw)
            while view:
                n=os.write(fd,view);require(n>0,'state-io-failure','Short write');view=view[n:]
            os.fsync(fd)
        finally:os.close(fd)
        os.fsync(self.fd)
        # Keep a durable marker until the published replacement is durable.
        temp='managed.next'
        os.link('managed.pending',temp,src_dir_fd=self.fd,dst_dir_fd=self.fd,follow_symlinks=False)
        os.replace(temp,'managed.json',src_dir_fd=self.fd,dst_dir_fd=self.fd)
        os.fsync(self.fd)
        os.unlink('managed.pending',dir_fd=self.fd);os.fsync(self.fd)
        self.context.recheck()

    def close(self):
        for attr in ('lock','fd'):
            fd=getattr(self,attr,None)
            if fd is not None:os.close(fd);setattr(self,attr,None)
