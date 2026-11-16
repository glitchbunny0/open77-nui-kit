#!/usr/bin/env bash
# rml-preview: probe documents (tests/rml-preview/*.rml) painted and compared with committed reference PNGs
# (tests/rml-preview/ref/, small tolerance), plus the notes the tool prints and its edge cases. Every check also runs
# against mutants of bin/rml-preview, each carrying ONE planted bug; each mutant must turn its check red.
#
#   tests/rml-preview.sh           run (from the kit root; NUIKIT_TMP is used for all output)
#   tests/rml-preview.sh --regen   repaint the reference PNGs with the current bin/rml-preview; look at every one
#                                  (the gradients and paths probes were checked against Chromium) before committing
set -uo pipefail
cd "${NUIKIT:-$(cd "$(dirname "$0")/.." && pwd)}"
if ! python3 -c 'import PIL' 2>/dev/null; then
    echo "skipped: no Pillow (rml-preview needs it)"
    exit 0
fi
host=$(bash scripts/build.sh | tail -1) || { echo "FAIL: building the host"; exit 1; }
NUIKIT_HOST="$host" exec python3 - "$@" <<'EOF'
import concurrent.futures, json, os, shutil, struct, subprocess, sys, tempfile
from PIL import Image, ImageChops

KIT = os.getcwd()
TMP = os.environ.get('NUIKIT_TMP') or tempfile.mkdtemp()
PROBES = os.path.join(KIT, 'tests', 'rml-preview')
REF = os.path.join(PROBES, 'ref')
TOOL = os.path.join(KIT, 'bin', 'rml-preview')
FONTS = os.path.join(KIT, 'examples', 'side-menu', 'fonts')
REGULAR, SEMIBOLD = os.path.join(FONTS, 'Rajdhani-Regular.ttf'), os.path.join(FONTS, 'Rajdhani-SemiBold.ttf')
FONT = ['--font', f'kitraj={REGULAR},{SEMIBOLD}']
PIXELS = ['gradients', 'images', 'clip', 'opacity', 'text', 'boxes', 'paths']
# a pixel differs when a channel is off by more than DIFF (anti-aliased text and resampling need room; gradients are
# plain arithmetic and get a tight one, so a blend curve change shows); a probe may have LIMIT differing pixels
DIFF, LIMIT = {'gradients': 12}, 200


def run(tool, doc, cases, out, *extra, font=FONT, env=None):
    os.makedirs(out, exist_ok=True)
    cf = os.path.join(out, 'cases.json')
    with open(cf, 'w') as fh:
        json.dump(cases, fh)
    return subprocess.run([sys.executable, tool, doc, cf, '--out', out, '--root', '.'] + font + list(extra),
                          cwd=PROBES, capture_output=True, text=True, env=dict(os.environ, **(env or {})))


def differing(a, b, diff=48):
    if a.size != b.size:
        return a.width * a.height
    d = ImageChops.difference(a.convert('RGB'), b.convert('RGB')).split()
    m = ImageChops.lighter(ImageChops.lighter(d[0], d[1]), d[2])
    return m.point(lambda v: 255 if v > diff else 0).histogram()[255]


def probe(name):
    def check(tool, out):
        r = run(tool, name + '.rml', [{'name': name, 'size': [640, 400]}], out)
        if r.returncode:
            return False, f'exit {r.returncode}: {r.stderr.strip()[-300:]}'
        n = differing(Image.open(os.path.join(out, name + '.png')), Image.open(os.path.join(REF, name + '.png')),
                      DIFF.get(name, 48))
        return n <= LIMIT, f'{n} pixels differ from ref/{name}.png'
    return check


def has(text, *needles):
    miss = [n for n in needles if n not in text]
    return (not miss), ('missing: ' + ' | '.join(miss)) if miss else 'all there'


def notes_missing(tool, out):
    r = run(tool, 'images.rml', [{'name': 'images', 'size': [640, 400]}], out)
    return has(r.stdout, 'MISSING image /img/nosuch.png')


def notes_font(tool, out):
    r = run(tool, 'text.rml', [{'name': 'text', 'size': [640, 400]}], out)
    # the host leaves text with no face out of the layout, as RmlUi does, and passes RmlUi's own warning on; a painter
    # given such text (an older host) lists it itself. Either way: listed, and nothing red painted.
    listed = (("'kitraj' [italic]" in r.stdout or "NO FONT FACE 'kitraj' 400 italic" in r.stdout)
              and ("'nosuchfont' [regular]" in r.stdout or "NO FONT FACE 'nosuchfont' 400" in r.stdout))
    img = Image.open(os.path.join(out, 'text.png')).convert('RGB')
    red = sum(1 for px in img.getdata() if px[0] > 200 and px[1] < 60 and px[2] < 60)
    return listed and red == 0, f'listed={listed}, red pixels={red}'



def notes_unpainted(tool, out):
    a = run(tool, 'boxes.rml', [{'name': 'boxes', 'size': [640, 400]}], out + '/a').stdout
    b = run(tool, 'images.rml', [{'name': 'images', 'size': [640, 400]}], out + '/b').stdout
    return has(a + b, 'NOT PAINTED decorator tiled-horizontal()', 'box-shadow (#s1)', 'NOT PAINTED <img> element #im')


FAKE = r'''#!/usr/bin/env python3
# a stand-in rmlhost: the layout of one case as a host following the contract (or an older one) prints it
import json, os, sys
up = os.environ.get('FAKE_UPPER') == '1'
els = [{"tag": "div", "id": "c", "cls": "", "x": 300, "y": 10, "w": 40, "h": 40, "bg": "#ff0000ff", "op": 1.0,
        "color": "#ffffffff", "bt": 0, "br": 0, "bb": 0, "bl": 0, "btc": "#00000000", "brc": "#00000000",
        "bbc": "#00000000", "blc": "#00000000", "radius": 0, "mask": "none", "deco": "none", "backdrop": "none",
        "clip": None},
       {"text": "STRA\u00dfE", "x": 10, "y": 60, "w": 0, "size": 40, "weight": 400, "family": "kitraj",
        "color": "#ffffffff", "op": 1.0, "ls": 0, "italic": False, "clip": [0, 0, 400, 100]}]
if up:
    els[1]["upper"] = True
print(json.dumps([{"name": "fake", "els": els, "warnings": ["font face substituted: 'nope' has no face"]}]))
'''


def runnable(p):
    """the path to run the Python script p as a program: p itself on Linux and macOS; on Windows p.cmd, written next to
    it (Windows starts no script by its #! line, and Python's subprocess starts only .exe and .cmd files)"""
    if os.name != 'nt':
        os.chmod(p, 0o755)
        return p
    with open(p + '.cmd', 'w', encoding='utf-8', newline='\r\n') as fh:
        fh.write(f'@"{sys.executable}" "{p}" %*\n')
    return p + '.cmd'


def fake_host():
    p = os.path.join(TMP, 'fakehost')
    if not os.path.exists(p):
        with open(p, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(FAKE)
    return runnable(p)


def host_warnings(tool, out):
    r = run(tool, 'text.rml', [{'name': 'fake', 'size': [400, 100]}], out, env={'NUIKIT_HOST': fake_host()})
    return has(r.stdout, "WARN font face substituted: 'nope' has no face")


def host_fields(tool, out):
    """the host's text is drawn as given (an old host's `upper: true` changes nothing); a box with clip null is painted"""
    a = run(tool, 'text.rml', [{'name': 'fake', 'size': [400, 100]}], out + '/a', env={'NUIKIT_HOST': fake_host()})
    b = run(tool, 'text.rml', [{'name': 'fake', 'size': [400, 100]}], out + '/b',
            env={'NUIKIT_HOST': fake_host(), 'FAKE_UPPER': '1'})
    if a.returncode or b.returncode:
        return False, (a.stderr + b.stderr).strip()[-300:]
    ia, ib = Image.open(out + '/a/fake.png'), Image.open(out + '/b/fake.png')
    n = differing(ia, ib)
    red = ia.convert('RGB').getpixel((320, 30))
    return n == 0 and red == (255, 0, 0), f'upper:true changes {n} pixels; clip-null box pixel {red}'


def patched_font(name, weight=None, italic=False):
    """a copy of Rajdhani Regular whose OS/2 / head tables claim another weight or style (its name stays Regular)"""
    p = os.path.join(TMP, name)
    data = bytearray(open(REGULAR, 'rb').read())
    n = struct.unpack('>H', data[4:6])[0]
    tables = {bytes(data[12 + 16 * i:16 + 16 * i]): struct.unpack('>I', data[20 + 16 * i:24 + 16 * i])[0] for i in range(n)}
    if weight:
        data[tables[b'OS/2'] + 4:tables[b'OS/2'] + 6] = struct.pack('>H', weight)
    if italic:
        sel = struct.unpack('>H', data[tables[b'OS/2'] + 62:tables[b'OS/2'] + 64])[0]
        data[tables[b'OS/2'] + 62:tables[b'OS/2'] + 64] = struct.pack('>H', (sel | 1) & ~0x40)
        mac = struct.unpack('>H', data[tables[b'head'] + 44:tables[b'head'] + 46])[0]
        data[tables[b'head'] + 44:tables[b'head'] + 46] = struct.pack('>H', mac | 2)
    with open(p, 'wb') as fh:
        fh.write(data)
    return p


def utf8_cases(tool, out):
    """cases reach the host as UTF-8, so a non-BMP character is one code point there (no \\ud83d surrogate escapes)"""
    rec = os.path.join(out, 'stdin.json')
    os.makedirs(out, exist_ok=True)
    wrap = os.path.join(out, 'host')   # records what the tool sends, then hands it to the real host
    with open(wrap, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(f'#!/usr/bin/env python3\nimport subprocess, sys\ndata = sys.stdin.buffer.read()\n'
                 f'open({rec!r}, "wb").write(data)\n'
                 f'sys.exit(subprocess.run([{os.environ["NUIKIT_HOST"]!r}] + sys.argv[1:], input=data).returncode)\n')
    r = run(tool, 'emoji.rml', [{'name': 'emoji', 'size': [400, 100], 'model': {'s': 'Loot \U0001F600 ready'}}], out,
            env={'NUIKIT_HOST': runnable(wrap)})
    sent = open(rec, 'rb').read() if os.path.exists(rec) else b''
    ok = r.returncode == 0 and '\U0001F600'.encode() in sent
    return ok, f'exit {r.returncode}, host stdin {sent[:80]!r} {r.stderr.strip()[-200:]}'


def font_tables(tool, out):
    heavy, ital = patched_font('heavy.ttf', weight=700), patched_font('ital.ttf', italic=True)
    r = run(tool, 'text.rml', [{'name': 'text', 'size': [640, 400]}], out, font=['--font', f'kitraj={REGULAR},{heavy},{ital}'])
    if r.returncode:
        return False, r.stderr.strip()[-300:]
    keys = sorted(json.load(open(os.path.join(out, '.fonts.json'))))
    ok = keys == ['kitraj|400', 'kitraj|400|i', 'kitraj|700'] and 'italic' not in r.stdout
    return ok, f'fonts.json keys {keys}' + ('; italic text still has no face' if 'italic' in r.stdout else '')


def font_duplicate(tool, out):
    r = run(tool, 'text.rml', [{'name': 'text', 'size': [640, 400]}], out, font=['--font', f'kitraj={REGULAR},{REGULAR}'])
    return r.returncode != 0 and 'both kitraj weight 400' in r.stderr, f'exit {r.returncode}: {r.stderr.strip()[-200:]}'


def compare_scaled(tool, out):
    refs = os.path.join(out, 'refs')
    os.makedirs(refs, exist_ok=True)
    Image.open(os.path.join(REF, 'gradients.png')).resize((1280, 800)).save(os.path.join(refs, 'gradients.png'))
    r = run(tool, 'gradients.rml', [{'name': 'gradients', 'size': [640, 400]}], out, '--compare', refs)
    if r.returncode:
        return False, r.stderr.strip()[-300:]
    c = Image.open(os.path.join(out, 'compare.png')).convert('RGB')
    # compare.png at half size: reference at (5, 22), preview at (330, 22), each 320 x 200
    left, right = c.crop((5, 22, 325, 222)), c.crop((330, 22, 650, 222))
    n = differing(left, right)
    return n <= LIMIT and 'scaled to the case size' in r.stdout, f'{n} pixels differ between the columns'


def crop_bad(tool, out):
    r = run(tool, 'gradients.rml', [{'name': 'gradients', 'size': [640, 400]}], out, '--sheet-crop', '500,500,100,100')
    return (r.returncode != 0 and '--sheet-crop wants' in r.stderr and 'Traceback' not in r.stderr,
            f'exit {r.returncode}: {r.stderr.strip()[-200:]}')


def no_cases(tool, out):
    os.makedirs(os.path.join(out, 'refs'), exist_ok=True)
    r = run(tool, 'gradients.rml', [], out, '--compare', os.path.join(out, 'refs'))
    return r.returncode == 0 and 'Traceback' not in r.stderr, f'exit {r.returncode}: {r.stderr.strip()[-200:]}'


def case_names(tool, out):
    r = run(tool, 'gradients.rml', [{'name': 'a/b', 'size': [64, 40]}], out)
    return r.returncode == 0 and os.path.exists(os.path.join(out, 'a_b.png')), f'exit {r.returncode}: {r.stderr.strip()[-200:]}'


def bg_missing(tool, out):
    r = run(tool, 'gradients.rml', [{'name': 'g', 'size': [64, 40]}], out, '--bg', os.path.join(out, 'nosuch.png'))
    return (r.returncode != 0 and '--bg image not found' in r.stderr and 'Traceback' not in r.stderr,
            f'exit {r.returncode}: {r.stderr.strip()[-200:]}')


def cases_bom(tool, out):
    """a cases file with a byte order mark: UTF-16 (what `>` writes in Windows PowerShell 5) and UTF-8"""
    os.makedirs(out, exist_ok=True)
    text = json.dumps([{'name': 'g', 'size': [64, 40]}])
    rcs = []
    for n, data in (('16', b'\xff\xfe' + text.encode('utf-16-le')), ('8', b'\xef\xbb\xbf' + text.encode())):
        cf = os.path.join(out, f'bom{n}.json')
        with open(cf, 'wb') as fh:
            fh.write(data)
        r = subprocess.run([sys.executable, tool, 'gradients.rml', cf, '--out', os.path.join(out, n), '--root', '.'] + FONT,
                           cwd=PROBES, capture_output=True, text=True)
        rcs.append((r.returncode, os.path.exists(os.path.join(out, n, 'g.png')), r.stderr.strip()[-120:]))
    return all(rc == 0 and png for rc, png, _ in rcs), f'UTF-16, UTF-8: {rcs}'


def strict(tool, out):
    a = run(tool, 'images.rml', [{'name': 'images', 'size': [640, 400]}], out + '/a', '--strict')
    b = run(tool, 'gradients.rml', [{'name': 'gradients', 'size': [640, 400]}], out + '/b', '--strict')
    return a.returncode == 1 and b.returncode == 0, f'with a missing image: exit {a.returncode}; clean: exit {b.returncode}'


CHECKS = {f'pixels: {p}': probe(p) for p in PIXELS}
CHECKS.update({
    'notes: a missing image is listed': notes_missing,
    'notes: text RmlUi has no face for is listed, not painted': notes_font,
    'notes: what is not painted is listed': notes_unpainted,
    'host: per-case warnings are printed': host_warnings,
    'host: text drawn as given (old `upper` ignored), clip null paints': host_fields,
    'emoji: cases reach the host as UTF-8': utf8_cases,
    'fonts: weight and style read from OS/2 and head': font_tables,
    'fonts: two files for one face are an error': font_duplicate,
    '--compare: a reference of another size is scaled': compare_scaled,
    '--sheet-crop: a bad rectangle is an error, not a traceback': crop_bad,
    'no cases: no sheet, no compare, no traceback': no_cases,
    'case names: a "/" does not leave --out': case_names,
    '--bg: a missing file is an error': bg_missing,
    '--strict: exit 1 on a missing image, 0 when clean': strict,
    'cases: a byte order mark (UTF-16 from PowerShell 5, UTF-8) is read': cases_bom,
})

# (check, planted bug, text in bin/rml-preview, replacement): each must turn its check red on its own
MUTANTS = [
    ('pixels: gradients', 'linear angle measured the wrong way round',
     "lv = (math.sin(angle), -math.cos(angle))", "lv = (math.sin(angle), math.cos(angle))"),
    ('pixels: gradients', '`to <corner>` taken as the default 180deg',
     "                    corner = {('right', 'top'): 0,", "                    angle, _ = math.pi, {('right', 'top'): 0,"),
    ('pixels: gradients', 'rgb()/hsl() stops not read',
     "    if s[:3] in ('rgb', 'hsl') and '(' in s:", "    if False:"),
    ('pixels: gradients', 'radial gradient with the closest instead of the farthest corner',
     "rr = near if kw == 'closest-corner' else far", "rr = near"),
    ('pixels: gradients', 'conic gradient counter-clockwise',
     "return 0.5 + math.atan2(-rx, ry) / (2 * math.pi)", "return 0.5 - math.atan2(-rx, ry) / (2 * math.pi)"),
    ('pixels: gradients', 'repeating gradients not repeated',
     "    if repeating:\n        t0, t1", "    if False:\n        t0, t1"),
    ('pixels: gradients', 'decorators painted in the border box by default',
     "area, amask = P, inner\n", "area, amask = (X0, Y0, X1, Y1), outer\n"),
    ('pixels: gradients', 'a decorator list painted front to back',
     "for one in reversed(split_top(deco, ',')):", "for one in split_top(deco, ','):"),
    ('pixels: gradients', 'stops blended linearly, not with smoothstep like RmlUi\'s renderers',
     "    return k * k * (3 - 2 * k)", "    return k"),
    ('pixels: images', 'image() with no fit keyword at natural size (the old default)',
     "out = {'src': toks[0].strip('\"\\''), 'orientation': 'none', 'fit': 'fill',",
     "out = {'src': toks[0].strip('\"\\''), 'orientation': 'none', 'fit': 'scale-none',"),
    ('pixels: images', 'alignment ignored (always centred)',
     "        dx, dy = offs\n", "        dx, dy = rnd((w - fw) / 2), rnd((h - fh) / 2)\n"),
    ('pixels: images', 'relative paths resolved against --root, not the declaring sheet',
     "            if path and ref in txt:", "            if False:"),
    ('pixels: images', 'orientation ignored',
     "    if o in ('flip-horizontal', 'rotate-180'):", "    if False:"),
    ('pixels: clip', 'the host\'s clip rectangle ignored',
     "x0, y0, x1, y1 = (0, 0, W, H) if clip is None else", "x0, y0, x1, y1 = (0, 0, W, H) if True else"),
    ('pixels: clip', 'backdrop blur ignores the clip',
     "self.composite(img, blurred, clip, (X0, Y0, X1, Y1))", "self.composite(img, blurred, None, (X0, Y0, X1, Y1))"),
    ('pixels: opacity', 'background opacity ignored',
     "bgc = rgba(e.get('bg'), op)", "bgc = rgba(e.get('bg'), 1.0)"),
    ('pixels: opacity', 'text opacity ignored',
     "x, col = e['x'], rgba(e['color'], e['op'])", "x, col = e['x'], rgba(e['color'], 1.0)"),
    ('pixels: text', 'text uppercased again by Python (the old double transform)',
     "for ch in e['text']:", "for ch in e['text'].upper():"),
    ('pixels: text', 'a missing weight takes the first face, not the nearest',
     "            if dist is None or dd < dist:", "            if dist is None:"),
    ('pixels: text', 'letter-spacing ignored',
     "x += f.getlength(ch) + e['ls']", "x += f.getlength(ch)"),
    ('pixels: boxes', 'border-radius ignored',
     "    if sum(r) <= 1:\n        return [0.0] * 4", "    if True:\n        return [0.0] * 4"),
    ('pixels: boxes', 'mask-image ignored',
     "layer.putalpha(ImageChops.multiply(layer.split()[3], ml.split()[3]))", "pass"),
    ('pixels: boxes', 'border sides as overlapping rectangles, not mitred',
     "            ImageDraw.Draw(sm).polygon(poly, fill=255)",
     "            ImageDraw.Draw(sm).rectangle([min(p[0] for p in poly), min(p[1] for p in poly), max(p[0] for p in poly), max(p[1] for p in poly)], fill=255)"),
    ('pixels: paths', 'cubic curves as straight lines',
     "            for s in range(1, 17):\n                u = s / 16\n                a, b, cc, dd",
     "            for s in range(16, 17):\n                u = s / 16\n                a, b, cc, dd"),
    ('pixels: paths', 'arcs as straight lines',
     "    if rx == 0 or ry == 0 or p0 == p1:", "    if True:"),
    ('pixels: paths', 'every subpath filled (no nonzero holes)',
     "acc = ImageChops.add(acc, m) if area >= 0 else ImageChops.subtract(acc, m)", "acc = ImageChops.add(acc, m)"),
    ('notes: a missing image is listed', 'a missing image not reported',
     "            if src is None:\n                notes.add(f'MISSING image",
     "            if src is None:\n                return None\n                notes.add(f'MISSING image"),
        ('notes: what is not painted is listed', 'unknown decorator types skipped silently',
     "        notes.add(f'NOT PAINTED {kind} {typ}()'", "        (f'NOT PAINTED {kind} {typ}()'"),
    ('notes: what is not painted is listed', 'sheet properties not scanned',
     "                if k in NOT_PAINTED and", "                if False and"),
    ('notes: what is not painted is listed', '<img> skipped silently',
     "        if e.get('tag') == 'img':", "        if False:"),
    ('host: per-case warnings are printed', 'host warnings dropped',
     "warns = [str(w) for w in (s.get('warnings') or [])]", "warns = []"),
    ('host: text drawn as given (old `upper` ignored), clip null paints', 'old `upper` field applied',
     "for ch in e['text']:", "for ch in (e['text'].upper() if e.get('upper') else e['text']):"),
    ('host: text drawn as given (old `upper` ignored), clip null paints', 'clip null taken as an empty clip',
     "x0, y0, x1, y1 = (0, 0, W, H) if clip is None else", "x0, y0, x1, y1 = (0, 0, 0, 0) if clip is None else"),
    ('emoji: cases reach the host as UTF-8', 'cases sent ASCII-escaped (surrogate pairs)',
     "input=json.dumps(cases, ensure_ascii=False)", "input=json.dumps(cases)"),
    ('fonts: weight and style read from OS/2 and head', 'usWeightClass ignored',
     "        weight = struct.unpack('>H', data[off + 4:off + 6])[0]", "        weight = 0"),
    ('fonts: weight and style read from OS/2 and head', 'italic flags ignored',
     "    return weight, italic\n", "    return weight, False\n"),
    ('fonts: two files for one face are an error', 'the second file silently wins',
     "            if key in seen:", "            if False:"),
    ('--compare: a reference of another size is scaled', 'reference pasted at its own size',
     "                    r = r.resize(size, Image.LANCZOS)", "                    pass"),
    ('--sheet-crop: a bad rectangle is an error, not a traceback', 'crop rectangle not validated',
     "if len(c) != 4 or c[2] <= c[0] or c[3] <= c[1]:", "if len(c) != 4:"),
    ('cases: a byte order mark (UTF-16 from PowerShell 5, UTF-8) is read', 'the byte order mark left in',
     "    for bom, name in BOMS:", "    for bom, name in ():"),
    ('no cases: no sheet, no compare, no traceback', 'compare built with no cases',
     "    if a.compare and tiles:", "    if a.compare:"),
    ('case names: a "/" does not leave --out', 'case name used as the file name as is',
     "    n = re.sub(r'[/\\\\\\x00]', '_', str(name))", "    n = str(name)"),
    ('--bg: a missing file is an error', 'missing --bg not checked',
     "    if a.bg and not os.path.isfile(a.bg):", "    if False:"),
    ('--strict: exit 1 on a missing image, 0 when clean', '--strict ignored',
     "    if a.strict and bad:", "    if False:"),
]


def mutant(i, old, new):
    src = open(TOOL, encoding='utf-8').read()
    if src.count(old) != 1:
        return None
    d = os.path.join(TMP, 'mutants', str(i))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'rml-preview')
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(src.replace(old, new))
    return p


def main():
    if '--regen' in sys.argv:
        os.makedirs(REF, exist_ok=True)
        for p in PIXELS:
            out = os.path.join(TMP, 'regen')
            r = run(TOOL, p + '.rml', [{'name': p, 'size': [640, 400]}], out)
            if r.returncode:
                sys.exit(r.stderr)
            shutil.copy(os.path.join(out, p + '.png'), os.path.join(REF, p + '.png'))
            print('wrote', os.path.join('tests', 'rml-preview', 'ref', p + '.png'))
        return 0
    jobs = [(name, None, fn, TOOL) for name, fn in CHECKS.items()]
    fail = 0
    for i, (name, bug, old, new) in enumerate(MUTANTS):
        p = mutant(i, old, new)
        if p is None:
            print(f'FAIL mutant "{bug}" no longer applies to bin/rml-preview (update it with the code)')
            fail = 1
        else:
            jobs.append((name, bug, CHECKS[name], p))

    def go(k):
        name, bug, fn, tool = jobs[k]
        try:
            return fn(tool, os.path.join(TMP, 'run', str(k)))
        except Exception as e:   # a check that crashes is red
            return False, f'{type(e).__name__}: {e}'
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        results = list(ex.map(go, range(len(jobs))))
    for (name, bug, _, _), (ok, detail) in zip(jobs, results):
        if bug is None:
            print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else ': ' + detail))
            fail |= not ok
        else:
            print(('ok   ' if not ok else 'FAIL ') + f'{name} <- mutant "{bug}"' + (' turns it red' if not ok else ' SURVIVED: ' + detail))
            fail |= ok
    n = sum(1 for j in jobs if j[1])
    print(f'rml-preview: {len(CHECKS)} checks, {n} mutants', 'FAILED' if fail else 'all red as they should be')
    return fail


sys.exit(main())
EOF
