# Data only; parsed with ast.literal_eval.
[['/bin/bash',
  '-eu',
  '-c',
  'set -eu\n'
  '[ "$(id -u)" != 0 ]\n'
  '[ "$(pwd -P)" = /image-build/source ]\n'
  'test ! -e /tools; test ! -e /sysroot\n'
  'test -z "$(gcc -print-sysroot)"\n'
  'for tool in msgfmt msgmerge xgettext bison perl python3 makeinfo findmnt getopt; do command -v "$tool"; '
  'done\n'
  "cat > parser.y <<'EOF'\n"
  '%{\n'
  '#include <stdio.h>\n'
  'int yylex(void); void yyerror(const char *s);\n'
  '%}\n'
  '%token NUMBER\n'
  '%%\n'
  'input: NUMBER \'+\' NUMBER { if ($1 + $3 != 42) YYABORT; puts("Bison generated parser passed"); };\n'
  '%%\n'
  "int yylex(void){static int n;switch(n++){case 0:yylval=19;return NUMBER;case 1:return '+';case "
  '2:yylval=23;return NUMBER;default:return 0;}}\n'
  'void yyerror(const char *s){fprintf(stderr,"%s\\n",s);}\n'
  'int main(void){return yyparse();}\n'
  'EOF\n'
  'bison -o parser.c parser.y\n'
  'cc parser.c -o parser\n'
  './parser\n'
  'perl -MConfig -MFile::Temp -MJSON::PP -e \'die unless $Config{prefix} eq "/usr"; print '
  'encode_json({answer=>6*7}),"\\n";\'\n'
  "python3 - <<'PY'\n"
  'import ast, decimal, zlib, json, subprocess, pathlib, sysconfig, _decimal\n'
  "assert decimal.Decimal('0.1') + decimal.Decimal('0.2') == decimal.Decimal('0.3')\n"
  "assert zlib.decompress(zlib.compress(b'Zog')) == b'Zog'\n"
  'assert ast.literal_eval(\'{"answer": 42}\')[\'answer\'] == 42\n'
  "assert subprocess.check_output(['perl','-e','print 42'], text=True) == '42'\n"
  "assert sysconfig.get_config_var('prefix') == '/usr'\n"
  "pathlib.Path('/image-build/output/python-capabilities.json').write_text(json.dumps({'version':__import__('sys').version,'decimal':_decimal.__libmpdec_version__,'zlib':zlib.ZLIB_RUNTIME_VERSION,'optional_ssl':'not "
  "required in temporary build'},indent=2))\n"
  "print('Python AST, decimal, compression, subprocess passed')\n"
  'PY\n'
  "cat > message.po <<'EOF'\n"
  'msgid "hello"\n'
  'msgstr "bonjour"\n'
  'EOF\n'
  'msgfmt -o message.mo message.po\n'
  "python3 - <<'PY'\n"
  'import gettext\n'
  "with open('message.mo','rb') as f: assert gettext.GNUTranslations(f).gettext('hello') == 'bonjour'\n"
  "print('Gettext compiled catalogue passed')\n"
  'PY\n'
  "printf '@setfilename example.info\\n@node Top\\n@top Example\\nZog build tools.\\n@bye\\n' > "
  'example.texi\n'
  'makeinfo example.texi -o example.info\n'
  'test -s example.info\n'
  'findmnt -n -T /image-build/source\n'
  'getopt -o a: -- -a value | grep value\n'
  "printf 'Expanded native build environment acceptance passed\\n' | tee "
  '/image-build/output/acceptance.txt\n']]
