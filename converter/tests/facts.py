#!/usr/bin/env python3
"""The RmlUi facts html2rml's mappings rest on, measured against real RmlUi 6.3 (the kit's host): every fact writes a
throwaway document, loads it (`check` for warnings and the element outline, `layout` for computed sizes and colours)
and asserts what RmlUi did. docs/converter.md lists the same facts; when RmlUi moves, this fails first.

  converter/tests/facts.py [-v]
"""
import json, os, re, subprocess, sys, tempfile
for _s in (sys.stdout, sys.stderr):   # UTF-8 and \n on every OS: a check's message may hold any character
    _s.reconfigure(encoding='utf-8', errors='backslashreplace', newline='\n')

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def host():
    tools = os.environ.get('HTML2RML_KIT') or KIT   # the mutation runs point it at the real kit
    r = subprocess.run([sys.executable, os.path.join(tools, 'scripts', 'build.py')], capture_output=True)
    if r.returncode != 0:
        sys.exit('facts: building the host failed:\n' + r.stderr.decode('utf-8', 'replace'))
    return r.stdout.decode('utf-8').strip().splitlines()[-1]


HOST = None
TMP = tempfile.mkdtemp(prefix='html2rml-facts-')
# image(a.png) in the facts below must name a file that exists: the host reports a missing image as RmlUi does
for _png in ('a.png', 'a b.png'):
    with open(os.path.join(TMP, _png), 'wb') as fh:
        fh.write(bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                               '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082'))


def doc(rcss, body, body_attrs=''):
    with open(os.path.join(TMP, 'f.rcss'), 'w') as fh:
        fh.write('div { display: block; }\nbody { font-family: x; }\n' + rcss)
    with open(os.path.join(TMP, 'f.rml'), 'w') as fh:
        fh.write('<rml><head><link type="text/rcss" href="f.rcss"/></head><body data-model="m"%s>%s</body></rml>'
                 % (body_attrs, body))
    return os.path.join(TMP, 'f.rml')


def warnings(rcss, body='<div id="e"></div>', body_attrs=''):
    """the RmlUi warnings for this sheet (font warnings left out)"""
    r = subprocess.run([HOST, 'check', doc(rcss, body, body_attrs), 'm'],
                       input=json.dumps([{'name': 'c', 'model': {'x': 1}}]), capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.startswith('WARN') and 'font face' not in l]


def outline(rcss, body):
    r = subprocess.run([HOST, 'check', doc(rcss, body), 'm'], input=json.dumps([{'name': 'c', 'model': {'x': 1}}]),
                       capture_output=True, text=True)
    return r.stdout


def layout(rcss, body, model=None):
    """layout mode: the element list"""
    fj = os.path.join(TMP, 'fonts.json')
    with open(fj, 'w') as fh:
        json.dump({f: {'ascent': 900, 'descent': 300, 'def': 500, 'adv': {}} for f in ('x|400', 'rajdhani|400')}, fh)
    r = subprocess.run([HOST, 'layout', doc(rcss, body), 'm', fj],
                       input=json.dumps([{'name': 'c', 'model': model or {'x': 1}}]), capture_output=True, text=True)
    return json.loads(r.stdout)[0]['els']


def boxes(rcss, body, model=None):
    """layout mode: {id: element json}, text runs under '#text'"""
    out = {}
    for e in layout(rcss, body, model):
        out[e.get('id') or ('#text' if 'text' in e else e.get('tag'))] = e
    return out


def ok_decl(decl):
    return not warnings('#e { %s }' % decl)


FACTS = []


def fact(text):
    def deco(fn):
        FACTS.append((text, fn))
        return fn
    return deco


@fact('rgba() alpha is read as 0-255: rgba(255, 0, 0, .5) is fully transparent; #RRGGBBAA is exact -> colours are written as hex')
def _():
    b = boxes('#a { width: 4dp; height: 4dp; background-color: rgba(255, 0, 0, .5); }'
              '#b { width: 4dp; height: 4dp; background-color: #FF000080; }', '<div id="a"/><div id="b"/>')
    return b['a']['bg'] == '#ff000000' and b['b']['bg'] == '#ff000080'


@fact('rgb() space/slash syntax, 130 of the CSS names and currentColor are syntax errors; the 18 basic names and transparent work')
def _():
    return (not ok_decl('color: rgb(255 0 0)') and not ok_decl('color: rgb(255 0 0 / 50%)')
            and not ok_decl('color: rebeccapurple') and not ok_decl('color: currentColor')
            and ok_decl('color: teal') and ok_decl('color: transparent') and ok_decl('color: hsla(10, 50%, 50%, .5)'))


@fact('rem is the document (body) font size, not a 16 px root -> rem is folded to dp with the page\'s own root size')
def _():
    b = boxes('body { font-size: 10dp; } #a { width: 3rem; height: 1dp; }', '<div id="a"/>')
    return b['a']['w'] == 30.0


@fact('em works for lengths and letter-spacing (kept as em)')
def _():
    b = boxes('#a { font-size: 10dp; width: 2em; height: 1dp; letter-spacing: .5em; }', '<div id="a">t</div>')
    return b['a']['w'] == 20.0 and b['#text']['ls'] == 5.0


@fact('letter-spacing in em is resolved again on every descendant (CSS computes it once, where it is declared) -> folded to dp')
def _():
    b = boxes('#a { font-size: 10dp; letter-spacing: .5em; } #a span { font-size: 20dp; }', '<div id="a"><span>t</span></div>')
    return b['#text']['ls'] == 10.0   # a browser gives 5


@fact('font-family takes one family; quotes are stripped and the name is lower-cased; a list is a syntax error')
def _():
    b = boxes('#a { font-family: "RajDhani"; }', '<div id="a">t</div>')
    return b['#text']['family'] == 'rajdhani' and not ok_decl('font-family: "Rajdhani", sans-serif')


@fact('the font shorthand has no line-height (`/1.2` is a syntax error); line-height: normal is an error, a number works')
def _():
    return (not ok_decl('font: 400 12px/1 Rajdhani') and ok_decl('font: 400 12px Rajdhani')
            and not ok_decl('line-height: normal') and ok_decl('line-height: 1.2'))


@fact('calc(), !important, inherit and initial are syntax errors')
def _():
    return (not ok_decl('width: calc(10dp + 2dp)') and not ok_decl('width: 9dp !important')
            and not ok_decl('color: inherit') and not ok_decl('width: initial'))


@fact('border takes width and colour only (a style keyword is an error); border-style does not exist; radii take no %')
def _():
    return (ok_decl('border: 1dp #fff') and not ok_decl('border: 1px solid #fff') and not ok_decl('border-style: solid')
            and not ok_decl('border-radius: 50%') and ok_decl('border-radius: 5dp'))


@fact('background is background-color only (an image in it is an error); images and gradients are decorators')
def _():
    return (ok_decl('background: #fff') and not ok_decl('background: #fff url(a.png)')
            and not ok_decl('background-image: url(a.png)') and ok_decl('decorator: image(a.png contain)')
            and ok_decl('decorator: image(a.png scale-none left top)') and ok_decl('decorator: image(a.png), linear-gradient(#fff, #000)'))


@fact('gradients: CSS directions, shapes and double-position stops parse; a colour hint and the turn unit do not')
def _():
    return (ok_decl('decorator: linear-gradient(to bottom right, #fff, #000)')
            and ok_decl('decorator: radial-gradient(ellipse at 50% 50%, #fff0 56%, #fff8 100%)')
            and ok_decl('decorator: conic-gradient(from 10deg at 50% 50%, #0000 0deg, #000 55deg)')
            and ok_decl('decorator: repeating-linear-gradient(90deg, #fff 0dp 1dp, #0000 1dp 6dp)')
            and not ok_decl('decorator: linear-gradient(90deg, #fff 10%, 30%, #000)')
            and not ok_decl('decorator: linear-gradient(0.25turn, #fff, #000)'))


@fact('mask-image takes the same decorators (image, gradients)')
def _():
    return ok_decl('mask-image: image(a.png)') and ok_decl('mask-image: linear-gradient(#000, #0000)')


@fact('drop-shadow wants the colour first: drop-shadow(#000 0dp 0dp 3dp); colour last is an error')
def _():
    return ok_decl('filter: drop-shadow(#5EF6FFcc 0dp 0dp 3dp)') and not ok_decl('filter: drop-shadow(0 0 3px #5EF6FFcc)')


@fact('transitions: CSS easing names (ease-out) and ms durations are errors; RmlUi tweens and seconds work, with a delay')
def _():
    return (not ok_decl('transition: opacity .25s ease-out') and not ok_decl('transition: opacity 250ms cubic-out')
            and ok_decl('transition: opacity 0.25s 0.1s cubic-out, width 0.1s linear-in-out'))


@fact('animation needs a duration; duration, tween, count, alternate, name in that order work; keyframes with only 50% load')
def _():
    return (not ok_decl('animation: pulse') and ok_decl('animation: 1.1s sine-in-out infinite alternate pulse')
            and not warnings('@keyframes pulse { 50% { opacity: .45; } } #e { animation: 1s cubic-out infinite pulse; }'))


@fact('transform function names are case-sensitive: skewX works, skewx is an error')
def _():
    return ok_decl('transform: skewX(10deg) translateZ(1dp)') and not ok_decl('transform: skewx(10deg)')


@fact('display: grid, position: sticky, overflow: clip, width: fit-content, text-align: start, align-items: start and opacity: 50% are errors')
def _():
    return not any(ok_decl(d) for d in ('display: grid', 'position: sticky', 'overflow: clip', 'width: fit-content',
                                        'text-align: start', 'align-items: start', 'opacity: 50%'))


@fact('inset, flex: none, gap, box-shadow (inset, lists), font-effect lists and backdrop-filter parse')
def _():
    return all(ok_decl(d) for d in ('inset: 0', 'flex: none', 'gap: 4dp', 'box-shadow: #000 0dp 0dp 2dp, #fff 1dp 1dp inset',
                                    'font-effect: shadow(1dp 1dp #000), glow(0dp 3dp 0dp 0dp #000)',
                                    'backdrop-filter: blur(4dp)'))


@fact('a layer pinned with inset: 0 in a sized, positioned flex item gets exactly the parent box (once divs are blocks)')
def _():
    b = boxes('#row { display: flex; width: 400dp; } #p { position: relative; width: 30dp; height: 20dp; margin-top: 12dp; '
              'flex: none; } #c { position: absolute; inset: 0; }', '<div id="row"><div id="p"><div id="c"></div></div></div>')
    return (b['c']['x'], b['c']['y'], b['c']['w'], b['c']['h']) == (b['p']['x'], b['p']['y'], 30.0, 20.0)


@fact('structural selectors match (nth-child, first-child, :not(compound)); :not() with a list, :is() and ::before never match, with no warning')
def _():
    o = outline('#w .k:nth-child(2) { display: none; } #w .k:not(.z) { height: 5dp; } #w .k:not(.z, .y) { width: 7dp; }'
                '#w .k:is(.y) { width: 9dp; } #w .k::before { width: 11dp; } #w { width: 50dp; }',
                '<div id="w"><div class="k z"></div><div class="k"></div><div class="k y"></div></div>')
    lines = [l.strip() for l in o.splitlines() if 'div.k' in l]
    return (len(lines) == 3 and '[none]' in lines[1] and lines[2].endswith('50x5') and lines[0].endswith('50x0')
            and 'WARN' not in o.replace('No font face', ''))


@fact('attribute selectors match; a hidden attribute hides nothing -> it becomes the html2rml-hidden class')
def _():
    o = outline('#w [data-x="1"] { height: 3dp; }', '<div id="w"><div class="a" data-x="1"></div><div class="b" hidden=""></div></div>')
    a = [l for l in o.splitlines() if 'div.a' in l][0]
    b = [l for l in o.splitlines() if 'div.b' in l][0]
    return a.strip().endswith('x3') and '[none]' not in b


@fact('an unknown pseudo-class (:focus-within) is accepted silently and never matches')
def _():
    o = outline('#w:focus-within { display: none; }', '<div id="w"></div>')
    return '[none]' not in o and not [l for l in o.splitlines() if l.startswith('WARN') and 'font face' not in l]


@fact('@import is an invalid at-rule and swallows the rule after it -> local imports are inlined')
def _():
    o = outline('@import url(x.css);\n#e { width: 1dp; height: 1dp; }', '<div id="e"></div>')
    return "Invalid at-rule identifier 'import'" in o and [l for l in o.splitlines() if 'div#e' in l][0].endswith('0x0')


@fact('custom properties cascade and inherit and var() resolves at compute time, with fallbacks; a var() inside a '
      'custom property resolves where that property is declared (as in CSS) -> html2rml --vars native keeps them')
def _():
    b = boxes('body { --w: 10dp; --b: var(--w); } .s { --w: 30dp; } #a { --w: 20dp; width: var(--b); height: var(--h, 2dp); }'
              '#c { width: var(--w); height: 1dp; }', '<div id="a"></div><div class="s"><div id="c"></div></div>')
    return (b['a']['w'], b['a']['h'], b['c']['w']) == (10.0, 2.0, 30.0)


@fact('var() overrides by attribute and :nth-child reach data-for rows (what static folding cannot do)')
def _():
    els = layout('.row { --c: #ff0000; background-color: var(--c); height: 1dp; } .row:nth-child(even) { --c: #00ff00; }'
                 '.row[data-s="x"] { --c: #0000ff; }', '<div class="row" data-for="it : items" data-attr-data-s="it">'
                 '{{it}}</div>', {'items': ['a', 'b', 'x']})
    return [e['bg'] for e in els if e.get('cls') == 'row'] == ['#ff0000ff', '#00ff00ff', '#0000ffff']


@fact('custom properties: !important makes the value invalid where it is used; a quoted string next to other values is '
      'a syntax error; on body, a variable set through body\'s class warns once (the class arrives after a first '
      'style pass), through the body tag it does not -> a lone :root is written as body')
def _():
    return (warnings('body { --c: #ff0000 !important; } #e { background-color: var(--c); }') != []
            and warnings('body { --f: "a", b; }') != [] and warnings('body { --f: "a"; }') == []
            and warnings('.k { --c: #f00; } body { color: var(--c); }', body_attrs=' class="k"') != []
            and warnings('body { --c: #f00; } body { color: var(--c); }') == [])


@fact(':last-child, :nth-last-child and :last-of-type never match data-for rows: the template element stays after them')
def _():
    els = layout('.r { height: 1dp; } .r:last-child { height: 3dp; } .r:nth-last-child(1) { width: 3dp; }'
                 '.r:last-of-type { width: 3dp; }', '<div><div class="r" data-for="it : items">{{it}}</div></div>',
                 {'items': [1, 2]})
    return [(e['h'], e['w'] == 3.0) for e in els if e.get('cls') == 'r'] == [(1.0, False), (1.0, False)]


@fact('the image decorator tiles (repeat, repeat-x, repeat-y) and aligns with px, % or keywords, not dp')
def _():
    return (ok_decl('decorator: image(a.png repeat left top)') and ok_decl('decorator: image(a.png repeat-x 10px 20px)')
            and ok_decl('decorator: image(a.png repeat-y 25% 75%)') and ok_decl('decorator: image("a b.png" scale-none left top)')
            and not ok_decl('decorator: image(a.png scale-none 10dp 20dp)'))


@fact('transform: translate() and skew() take two arguments, scale() numbers: translate(10dp), skew(10deg) and '
      'scale(50%) are errors')
def _():
    return (not ok_decl('transform: translate(10dp)') and ok_decl('transform: translate(10dp, 0dp)')
            and not ok_decl('transform: skew(10deg)') and ok_decl('transform: skew(10deg, 0deg)')
            and not ok_decl('transform: scale(50%)') and ok_decl('transform: scale(0.5)'))


@fact('transition: `all` can not be part of a list')
def _():
    return (not ok_decl('transition: all 0.2s linear-in-out, opacity 0.3s linear-in-out')
            and ok_decl('transition: all 0.2s linear-in-out'))


@fact('gradients: a radial shape goes before its size; `in <colour space>` and a 4-value `at` position are errors')
def _():
    return (ok_decl('decorator: radial-gradient(circle closest-side, #fff, #000)')
            and not ok_decl('decorator: radial-gradient(closest-side circle, #fff, #000)')
            and not ok_decl('decorator: linear-gradient(90deg in oklab, #fff, #000)')
            and not ok_decl('decorator: radial-gradient(circle at left 10dp top 20dp, #fff, #000)'))


@fact('lab(), lch(), oklab(), oklch() parse (space syntax, alpha 0-1); a CSS system colour (canvastext) is an error')
def _():
    return (ok_decl('color: oklch(63% 0.25 30 / 0.8)') and ok_decl('background-color: lab(50% 40 59.5)')
            and ok_decl('color: lch(50% 40 180)') and not ok_decl('color: canvastext'))


def main(argv):
    global HOST
    HOST = host()
    bad = 0
    for text, fn in FACTS:
        try:
            good = fn()
        except Exception as e:   # a fact that cannot even run is a failure
            good, text = False, f'{text} ({e})'
        bad += not good
        if not good or '-v' in argv:
            print(('ok    ' if good else 'FAIL  ') + text)
    print(f'facts: {len(FACTS) - bad}/{len(FACTS)} hold in real RmlUi')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
