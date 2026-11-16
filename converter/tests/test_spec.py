#!/usr/bin/env python3
"""converter/rmlui_spec.py is generated from RmlUi's own property registry; this test regenerates it from the RmlUi
checkout the kit builds against and fails when the two differ (a new RmlUi pin: run with --regen and review).

  converter/tests/test_spec.py [--regen]
"""
import os, re, subprocess, sys
for _s in (sys.stdout, sys.stderr):   # UTF-8 and \n on every OS: a check's message may hold any character
    _s.reconfigure(encoding='utf-8', errors='backslashreplace', newline='\n')

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(KIT, 'converter', 'rmlui_spec.py')


def rmlui_dir():
    r = subprocess.run([sys.executable, os.path.join(KIT, 'scripts', 'build.py')], capture_output=True)
    if r.returncode != 0:
        sys.exit('test_spec: building the host failed:\n' + r.stderr.decode('utf-8', 'replace'))
    return os.path.dirname(os.path.dirname(r.stdout.decode('utf-8').strip().splitlines()[-1]))   # <dir>/build/rmlhost


def generate(src):
    body = src[src.index('void StyleSheetSpecification::RegisterDefaultProperties'):]
    lines = ['"""Generated from RmlUi 6.3 Source/Core/StyleSheetSpecification.cpp by converter/tests/test_spec.py --regen.',
             'Do not edit: every property RmlUi registers, its value parsers and keywords, and its shorthands."""',
             'PROPERTIES = {']
    for m in re.finditer(r'RegisterProperty\(PropertyId::\w+,\s*"([^"]+)",\s*"([^"]*)",\s*(true|false),\s*(true|false)\)'
                         r'((?:\s*\.\w+\([^;]*?\))*)\s*;', body, re.S):
        kinds, kws = [], []
        for pm in re.finditer(r'\.AddParser\("(\w+)"(?:,\s*"([^"]*)")?\)', m.group(5)):
            if pm.group(1) == 'keyword':
                kws += [x.strip().split('=')[0] for x in pm.group(2).split(',')]
            else:
                kinds.append(pm.group(1))
        lines.append(f'    {m.group(1)!r}: ({tuple(kinds)!r}, {tuple(kws)!r}),')
    lines += ['}', 'SHORTHANDS = {']
    for m in re.finditer(r'RegisterShorthand\(ShorthandId::\w+,\s*"([^"]+)",\s*"([^"]+)",\s*ShorthandType::(\w+)\)', body):
        lines.append(f'    {m.group(1)!r}: ({tuple(x.strip() for x in m.group(2).split(","))!r}, {m.group(3)!r}),')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main(argv):
    src = open(os.path.join(rmlui_dir(), 'Source', 'Core', 'StyleSheetSpecification.cpp'), encoding='utf-8').read()
    new = generate(src)
    if '--regen' in argv:
        with open(OUT, 'w') as fh:
            fh.write(new)
        print('spec: regenerated')
        return 0
    if open(OUT).read() != new:
        print('spec: FAIL converter/rmlui_spec.py differs from the RmlUi checkout (run with --regen and review)')
        return 1
    print('spec: ok (%d properties, %d shorthands)' % (new.split('SHORTHANDS')[0].count('\n    '),
                                                    new.split('SHORTHANDS')[1].count('\n    ')))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
