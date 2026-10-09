"""Recognize recorded shell invocation options; never interpret or execute a body."""
from pathlib import PurePosixPath

SHELLS = {'sh', 'bash', 'dash', 'ksh', 'zsh'}
SHORT = set('abefhiklmnprstuvxBCEHPT')
BASH_LONG = {'--norc', '--noprofile', '--posix', '--restricted', '--verbose',
             '--login', '--debugger', '--noediting'}


def inline_shell(argv):
    if not argv or PurePosixPath(argv[0]).name not in SHELLS:
        return dict(status='not-shell', interpreter=None, script=None)
    shell = PurePosixPath(argv[0]).name
    result = dict(status='no-inline-script', interpreter=argv[0], script=None)
    command_string = False
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == '--':
            index += 1
            break
        if word in ('-', '+') or not word.startswith(('-', '+')):
            break
        if word.startswith('--'):
            if shell == 'bash' and word in BASH_LONG:
                index += 1
                continue
            if shell == 'bash' and word in ('--rcfile', '--init-file') and index + 1 < len(argv):
                index += 2
                continue
            return dict(result, status='unsupported-options')
        letters = word[1:]
        for offset, option in enumerate(letters):
            if option == 'c' and word[0] == '-':
                command_string = True
            elif option in ('o', 'O'):
                # Only unambiguous separate option-name operands are supported.
                if option == 'O' and shell != 'bash':
                    return dict(result, status='unsupported-options')
                if offset != len(letters) - 1 or index + 1 >= len(argv) or argv[index + 1].startswith(('-', '+')):
                    return dict(result, status='unsupported-options')
                index += 1
            elif option not in SHORT:
                return dict(result, status='unsupported-options')
        index += 1
    if command_string:
        if index >= len(argv):
            return dict(result, status='missing-command-string')
        return dict(result, status='captured', script=argv[index])
    return result
