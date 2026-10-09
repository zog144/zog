"""Private worker protocol. A receipt here alone is not daemon admission."""
import os
import sys
from .state_contract import StateError, canonical, decode, fields, require
from .state_initialize import authorization, receipt_valid
from .state_inspect import inspect_live
from .state_probe import probe_live


def run(request):
    require(os.geteuid() == 970 and os.getegid() == 970, 'worker-account', 'UID/GID 970 required')
    fields(request, 'action authorization receipt')
    require(request['action'] in ('prepare', 'load-existing'), 'worker-action', 'unsupported action')
    with inspect_live() as context:
        auth = authorization(context.bundle)
        require(request['authorization'] == auth, 'authorization-conflict', 'worker bootstrap mismatch')
        if request['action'] == 'prepare':
            require(context.bundle['bootstrap']['mode'] == 'fresh' and request['receipt'] is None,
                    'initialization-not-authorized', 'fresh prepare only')
        else: receipt_valid(request['receipt'], auth)
        probe_live()
        context.recheck()
        from zog.host_identify.initialization import prepare, load_existing
        root = auth['identity_directory']
        if request['action'] == 'prepare':
            receipt = prepare(root, auth)
        else:
            load_existing(root, request['receipt'])
            receipt = request['receipt']
        receipt_valid(receipt, auth)
        context.recheck()
        return receipt


def main():
    try:
        result = run(decode(sys.stdin.buffer.read(65537)))
        sys.stdout.buffer.write(canonical(result))
        return 0
    except (OSError, StateError, ValueError, ImportError):
        # Never serialize exception locals or private material into diagnostics.
        print('identity worker refused; inspect protected state before retry', file=sys.stderr)
        return 2


if __name__ == '__main__': sys.exit(main())
