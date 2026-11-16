"""html2rml command line (bin/html2rml)."""
import argparse, json, os, sys
from .convert import convert, report_md

USAGE = """html2rml: convert a WebUI page (HTML + CSS, RmlUi binding syntax kept) into an RmlUi document and sheet.

  html2rml PAGE.html [--css extra.css ...] --out DIR [--name NAME] [--canvas 1920x1080] [--px-per-dp 1]
           [--root DIR] [--vars fold|native] [--strict] [--report md|json]

Writes DIR/NAME.rml, DIR/NAME.rcss and DIR/NAME.report.md (+ DIR/NAME.report.json with --report json). The report
lists everything that could not be mapped one to one, with file:line, what it was and what to do instead.
  --canvas     the design canvas: @media is evaluated for it and vw/vh become dp on it (default 1920x1080)
  --px-per-dp  CSS px per dp (default 1: 1 px = 1 dp at 1080p; 2 for a page drawn at 4K)
  --root       the resource folder: image and font paths are written from it (/web/assets/x.png), as Open77 resolves
               them; without it they are relative to DIR
  --vars       fold (default): var() and custom properties folded from the page's static cascade; native: kept
               for RmlUi 6.3 to resolve (states, attributes, data-for rows follow at run time), folded only where
               RmlUi could not take them
  --strict     exit 1 when the report has any item
Exit status: 0 written, 1 written with --strict and a non-empty report, 2 usage or input problem."""


def main(argv=None):
    for s in (sys.stdout, sys.stderr):   # UTF-8 and \n on every OS (a Windows pipe gets the ANSI code page and \r\n)
        if hasattr(s, 'reconfigure'):
            s.reconfigure(encoding='utf-8', errors='backslashreplace', newline='\n')
    ap = argparse.ArgumentParser(prog='html2rml', usage=USAGE, add_help=False)
    ap.add_argument('page', nargs='?')
    ap.add_argument('--css', action='append', default=[])
    ap.add_argument('--out')
    ap.add_argument('--name')
    ap.add_argument('--canvas', default='1920x1080')
    ap.add_argument('--px-per-dp', type=float, default=1.0)
    ap.add_argument('--root')
    ap.add_argument('--vars', choices=('fold', 'native'), default='fold')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--report', choices=('md', 'json'), default='md')
    ap.add_argument('-h', '--help', action='store_true')
    a = ap.parse_args(argv)
    if a.help or not a.page or not a.out:
        print(USAGE)
        return 0 if a.help else 2
    if not os.path.exists(a.page):
        print(f'html2rml: page not found: {a.page}', file=sys.stderr)
        return 2
    for c in a.css:
        if not os.path.exists(c):
            print(f'html2rml: stylesheet not found: {c}', file=sys.stderr)
            return 2
    try:
        w, h = [int(x) for x in a.canvas.lower().split('x')]
    except ValueError:
        print('html2rml: --canvas wants WxH, e.g. 1920x1080', file=sys.stderr)
        return 2
    if a.px_per_dp <= 0:
        print('html2rml: --px-per-dp must be > 0', file=sys.stderr)
        return 2
    os.makedirs(a.out, exist_ok=True)
    c, rml, rcss = convert(a.page, a.out, a.name, a.css, (w, h), a.px_per_dp, a.root, a.vars)
    base = os.path.join(a.out, c.name)
    with open(base + '.rml', 'w', encoding='utf-8', newline='\n') as fh:   # LF on every OS: the same bytes everywhere
        fh.write(rml)
    with open(base + '.rcss', 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(rcss)
    with open(base + '.report.md', 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(report_md(c))
    if a.report == 'json':
        with open(base + '.report.json', 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'page': os.path.basename(c.page), 'canvas': [w, h], 'px_per_dp': a.px_per_dp, 'vars': a.vars,
                       'fonts': c.fonts, 'items': c.report.items}, fh, indent=1)
            fh.write('\n')
    n = len(c.report.items)
    print(f'html2rml: wrote {base}.rml, {base}.rcss; report: {n} item(s) in {base}.report.md')
    return 1 if a.strict and n else 0


if __name__ == '__main__':
    sys.exit(main())
