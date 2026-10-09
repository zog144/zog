"""Fixed Unix-socket read-only box-control client; no arbitrary command bridge."""
import json
import os
import socket
import stat
import struct
from zog.host_identify.managed import identifier

PATH='/run/box-control/host-discover.sock'


class Gateway:
    def inspect(self,request_id,runtime_id):
        identifier(request_id);identifier(runtime_id)
        # A socket inode can be replaced; SO_PEERCRED authenticates the actual
        # connected server as well as checking the provisioned path.
        for path in ('/run','/run/box-control'):
            value=os.lstat(path)
            if not stat.S_ISDIR(value.st_mode) or value.st_uid not in (0,971) or value.st_mode&0o022:
                raise PermissionError('Unsafe gateway directory')
        value=os.lstat(PATH)
        if not stat.S_ISSOCK(value.st_mode) or (value.st_uid,value.st_gid,stat.S_IMODE(value.st_mode))!=(971,973,0o660):
            raise PermissionError('Unsafe gateway socket')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.settimeout(5);client.connect(PATH)
            pid,uid,gid=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=971:raise PermissionError('Unexpected controller peer')
            client.sendall(json.dumps(dict(version=1,request_id=request_id,operation='inspect',runtime_id=runtime_id)).encode()+b'\n')
            raw=bytearray()
            while len(raw)<=32768:
                chunk=client.recv(min(4096,32769-len(raw)))
                if not chunk:break
                raw.extend(chunk)
                if b'\n' in raw:break
            if len(raw)>32768 or not raw.endswith(b'\n') or raw.count(b'\n')!=1:raise ValueError('Invalid gateway frame')
            value=json.loads(raw)
            if set(value)!={'version','request_id','status','result'} or value['version']!=1 or value['request_id']!=request_id or value['status']!='completed':
                raise ValueError('Controller did not complete inspection')
            return value['result']
