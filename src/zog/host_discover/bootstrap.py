"""Offline STATE policy diagnostics; never an admission or authorization token."""
import argparse
import json
from zog.host_install.state_contract import StateError, decode, validate
from zog.host_install.state_gate import decide

# Compatibility names for callers; the old two-record proposal is unsupported.
ContractError = StateError
parse = decode


def evaluate(bundle, evidence):
    validate(bundle)
    decision = decide(bundle, evidence)
    return {"schema": 1, "kind": "zog-host-offline-preflight",
            "identity_action": decision["identity_action"], "code": decision["code"],
            "policy_control_allowed": decision["control_allowed"],
            "live_admission": False, "remote_control_enabled": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', required=True)
    p.add_argument('--evidence', required=True, help='Synthetic evidence, never runtime authorization')
    args = p.parse_args()
    def read(path):
        with open(path, 'rb') as stream:
            return decode(stream.read(65537))
    try:
        result = evaluate(read(args.bundle), read(args.evidence))
    except (StateError, OSError) as exc:
        p.exit(2, getattr(exc, 'code', 'offline-input-unavailable') + '\n')
    print(json.dumps(result, sort_keys=True))
    if result['identity_action'] in ('block', 'recovery-only'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
