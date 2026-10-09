set -eu
work=$(mktemp -d /tmp/zog-systemd-generators-XXXXXX)
trap 'rm -rf "$work"' EXIT
cd "$work"
cat > keywords <<'GPERF'
%{
#include <string.h>
%}
%%
alpha
beta
%%
GPERF
gperf -L ANSI-C keywords > generated.c
cat >> generated.c <<'C'
#include <assert.h>
int main(void) {
  assert(in_word_set("alpha", 5));
  assert(in_word_set("beta", 4));
  assert(!in_word_set("absent", 6));
  return 0;
}
C
gcc generated.c -o probe
./probe
python3 - <<'PYCHECK'
from markupsafe import Markup, escape
import markupsafe._speedups as native
assert native.__file__.endswith('.so'), native.__file__
assert str(escape('<&>')) == '&lt;&amp;&gt;'
assert str(Markup('<b>%s</b>') % '<unsafe>') == '<b>&lt;unsafe&gt;</b>'
assert Markup('&lt;b&gt;').unescape() == '<b>'
print('ZOG_MARKUPSAFE_NATIVE_PASS')
from jinja2 import Environment, DictLoader, StrictUndefined, UndefinedError
from markupsafe import Markup
loader=DictLoader({'unit':'[Unit]\nDescription={{ description }}\n[Service]\nExecStart={{ executable }}\n','base':'{% block content %}base{% endblock %}','child':'{% extends "base" %}{% block content %}{{ value }}{% endblock %}'})
env=Environment(loader=loader,undefined=StrictUndefined)
assert env.get_template('unit').render(description='Zog fixture',executable='/usr/bin/true') == '[Unit]\nDescription=Zog fixture\n[Service]\nExecStart=/usr/bin/true'
assert env.get_template('child').render(value='inherited') == 'inherited'
assert Environment(autoescape=True).from_string('{{ value }}').render(value='<&>') == '&lt;&amp;&gt;'
try:env.from_string('{{ missing }}').render()
except UndefinedError:pass
else:raise AssertionError('undefined value accepted')
print('ZOG_JINJA2_GENERATION_PASS')
PYCHECK
printf '%s\n' ZOG_SYSTEMD_GENERATORS_INSTALLED_PASS
