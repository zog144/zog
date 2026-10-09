"""A successful runner process must not hide missing or incomplete test results."""
import ast
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest

RECIPE = Path(__file__).parents[1]/'project/package/sqlite/stages/final/build.py'

@pytest.mark.parametrize('case', ['passed', 'failed', 'running', 'omitted', 'empty', 'zero-tests', 'missing-regression', 'missing-db'])
def test_sqlite_result_gate(tmp_path, case):
    rows=[('test/'+name+'.test','done',10,0) for name in ('sessionnoact','shell1','zipfile')]
    if case in ('failed','running','omitted'):
        rows[0]=(rows[0][0], {'failed':'failed','running':'running','omitted':'omit'}[case],10,1 if case=='failed' else 0)
    if case=='empty': rows=[]
    if case=='zero-tests': rows=[(n,s,0,e) for n,s,_,e in rows]
    if case=='missing-regression': rows.pop()
    if case!='missing-db':
        with sqlite3.connect(tmp_path/'testrunner.db') as db:
            db.execute('CREATE TABLE jobs(displayname,state,ntest,nerr)')
            db.executemany('INSERT INTO jobs VALUES(?,?,?,?)', rows)
    cli=tmp_path/'sqlite3'
    cli.write_text('#!'+sys.executable+'\nimport sqlite3,sys\ndb=sqlite3.connect("file:"+sys.argv[2]+"?mode=ro",uri=True)\nfor row in db.execute(sys.argv[3]): print("|".join(str(v) for v in row))\n')
    cli.chmod(0o755)
    command=ast.literal_eval(RECIPE.read_text())['test'][0][-1]
    gate=command[command.index('./sqlite3 -readonly'):]
    result=subprocess.run(['bash','-eu','-o','pipefail','-c',gate],cwd=tmp_path,capture_output=True,text=True)
    assert (result.returncode==0)==(case=='passed'), result.stdout+result.stderr
