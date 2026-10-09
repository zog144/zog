"""Guard the shared wheel/installed-root RFC 8032 acceptance fixture."""
import ast
from pathlib import Path

PROJECT = Path(__file__).parents[1] / 'project'


def test_ed25519_fixture_is_well_formed_and_identical_in_both_checks():
    shell = (PROJECT / 'bootstrap/cryptography-check.sh').read_text()
    installed = shell.split("<<'ZOG_CRYPTOGRAPHY'\n")[1].split('\nZOG_CRYPTOGRAPHY')[0] + '\n'
    recipe = ast.literal_eval((PROJECT / 'package/python-cryptography/stages/final/build.py').read_text())
    command = recipe['test'][0][-1]
    wheel = command.split("<<'ZOG_WHEEL'\n")[1].split('\nZOG_WHEEL')[0]
    calls = [n for n in ast.walk(ast.parse(wheel)) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'exec']
    assert len(calls) == 1
    assert ast.literal_eval(calls[0].args[0]) == installed
    tree = ast.parse(installed)
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and isinstance(n.targets[0], ast.Name)
                      and n.targets[0].id == 'expected_signature')
    encoded = ast.literal_eval(assignment.value.args[0])
    # Decoding rejects the original odd-length (129-digit) transcription error.
    assert len(bytes.fromhex(encoded)) == 64
    assert any(isinstance(n, ast.Assert) and "len(expected_signature) == 64" in ast.unparse(n)
               for n in tree.body)
