"""Declarations: one CSS declaration (or a rule's background/mask group) -> RCSS declarations + issues.
Every mapping here was checked against real RmlUi 6.3 (docs/converter.md lists the facts and how)."""
import math, os, re
from . import css_values as V
from .css_values import ValueIssue
from .rmlui_spec import PROPERTIES, SHORTHANDS


class Issue:
    def __init__(self, what, todo, kind='css'):
        self.what, self.todo, self.kind = what, todo, kind


# ---- easing: CSS timing functions -> the nearest RmlUi tween (max error over the curve measured by _fit)
TWEEN_FAMILIES = ('sine', 'quadratic', 'cubic', 'quartic', 'quintic', 'exponential', 'circular', 'back', 'linear')
CSS_EASE = {'ease': (0.25, 0.1, 0.25, 1), 'ease-in': (0.42, 0, 1, 1), 'ease-out': (0, 0, 0.58, 1),
            'ease-in-out': (0.42, 0, 0.58, 1), 'linear': (0, 0, 1, 1)}


def _tween_fn(name):
    fam, mode = re.match(r'^(\w+)-(in-out|in|out)$', name).groups()
    f = {'sine': lambda t: 1 - math.cos(t * math.pi / 2), 'quadratic': lambda t: t * t, 'cubic': lambda t: t ** 3,
         'quartic': lambda t: t ** 4, 'quintic': lambda t: t ** 5,
         'exponential': lambda t: t if t in (0, 1) else math.exp(7.24 * (t - 1)),   # RmlUi's Tween.cpp
         'back': lambda t: t * t * (2.70158 * t - 1.70158),
         'circular': lambda t: 1 - math.sqrt(max(0.0, 1 - t * t)), 'linear': lambda t: t}[fam]
    if mode == 'in':
        return f
    if mode == 'out':
        return lambda t: 1 - f(1 - t)
    return lambda t: f(2 * t) / 2 if t < 0.5 else 1 - f(2 - 2 * t) / 2


def _bezier(p1x, p1y, p2x, p2y):
    def y(x):
        lo, hi = 0.0, 1.0
        for _ in range(50):
            t = (lo + hi) / 2
            if 3 * (1 - t) ** 2 * t * p1x + 3 * (1 - t) * t * t * p2x + t ** 3 < x:
                lo = t
            else:
                hi = t
        t = (lo + hi) / 2
        return 3 * (1 - t) ** 2 * t * p1y + 3 * (1 - t) * t * t * p2y + t ** 3
    return y


def fit_tween(p):
    """the RmlUi tween closest to a cubic-bezier (max |y| difference over x in [0, 1]) -> (name, error)"""
    f = _bezier(*p)
    best = None
    for fam in TWEEN_FAMILIES:
        for mode in ('in', 'out', 'in-out'):
            name = f'{fam}-{mode}'
            g = _tween_fn(name)
            err = max(abs(f(i / 100) - g(i / 100)) for i in range(101))
            if best is None or err < best[1] - 1e-9:
                best = (name, err)
    if best[0].startswith('linear'):
        best = ('linear-in-out', best[1])
    return best


EASE_MAP = {k: fit_tween(v)[0] for k, v in CSS_EASE.items()}
RML_TWEENS = {f'{f}-{m}' for f in TWEEN_FAMILIES + ('bounce', 'elastic') for m in ('in', 'out', 'in-out')}


def tween_of(word, issues):
    """a CSS timing-function word/function -> RmlUi tween name, or None if the word is not one"""
    if word[0] == 'ident':
        n = word[1].lower()
        if n in EASE_MAP:
            return EASE_MAP[n]
        if n in RML_TWEENS:
            return n
        if n in ('step-start', 'step-end'):
            issues.append(Issue(f'timing function {n}', 'RmlUi has no steps: the nearest tween is linear-in-out'))
            return 'linear-in-out'
        return None
    if word[0] == 'func' and word[1] == 'cubic-bezier':
        nums = [t[1] for t in word[2] if t[0] == 'num']
        if len(nums) == 4:
            name, err = fit_tween(nums)
            issues.append(Issue(f'cubic-bezier({", ".join(V.fmt(x) for x in nums)})',
                                f'RmlUi has named tweens only: written as {name} (max error {err:.2f} of the range)'))
            return name
    if word[0] == 'func' and word[1] == 'steps':
        issues.append(Issue('steps() timing', 'RmlUi has no steps: written as linear-in-out'))
        return 'linear-in-out'
    if word[0] == 'func' and word[1] == 'linear':
        issues.append(Issue('linear() timing with stops', 'written as linear-in-out'))
        return 'linear-in-out'
    return None


def is_time(w):
    return len(w) == 1 and w[0][0] == 'num' and w[0][2] == 's'


def is_len(t, zero_ok=True):
    return t[0] == 'num' and (t[2] in ('dp', 'em', '%', 'x', 'vw', 'vh') or (zero_ok and t[1] == 0 and t[2] == ''))


def len_str(t):
    """a length token as RCSS text; a unitless 0 stays 0"""
    if t[0] == 'num' and t[1] == 0 and t[2] == '':
        return '0'
    return V.ser([t])


# paint properties Open77's NativeUI adds for <path>/<shape> (vanilla RmlUi rejects them; rml-check allows them)
OPEN77_PROPS = {'fill', 'stroke', 'stroke-width', 'stroke-linejoin', 'stroke-linecap', 'stroke-dasharray',
                'stroke-dashoffset', 'trim-start', 'trim-end', 'trim-offset'}
GLOBAL_KW = {'inherit', 'initial', 'unset', 'revert', 'revert-layer'}
NO_COLOR_PROPS = {'font-family', 'font', 'animation', 'animation-name', 'transition', 'transition-property',
                  'will-change', 'content', 'counter-reset', 'counter-increment', 'cursor', 'grid-area',
                  'grid-template-areas', 'list-style', 'list-style-type'}

# CSS properties with no RmlUi counterpart; the reason/todo shown in the report
UNSUPPORTED = {
    'user-select': 'RmlUi has no text selection: nothing to do',
    'outline': 'RmlUi has no outline: use a border or an extra element',
    'content': 'only meaningful on ::before/::after, which RmlUi lacks',
    'object-fit': 'size the <img> with width/height (or use a decorator: image(src contain|cover))',
    'object-position': 'size and place the <img> itself',
    'aspect-ratio': 'write width and height',
    'will-change': 'nothing to do',
    'contain': 'nothing to do',
    'isolation': 'nothing to do',
    'mix-blend-mode': 'RmlUi has no blend modes',
    'background-blend-mode': 'RmlUi has no blend modes',
    'appearance': 'RmlUi form controls have no native look: nothing to do',
    'resize': 'RmlUi has no resizable boxes',
    'touch-action': 'nothing to do',
    'scroll-behavior': 'RmlUi scrolls instantly',
    'text-rendering': 'nothing to do',
    'font-smoothing': 'nothing to do',
    'image-rendering': 'nothing to do',
    'order': 'reorder the elements in the markup',
    'justify-items': 'grid only: RmlUi has no grid',
    'justify-self': 'grid only: RmlUi has no grid',
    'place-self': 'grid only: RmlUi has no grid',
    'list-style': 'RmlUi draws no list markers: put the marker in the markup',
    'list-style-type': 'RmlUi draws no list markers: put the marker in the markup',
    'list-style-position': 'RmlUi draws no list markers',
    'list-style-image': 'RmlUi draws no list markers: use an <img> or a decorator',
    'counter-reset': 'RmlUi has no counters: write the numbers from the client',
    'counter-increment': 'RmlUi has no counters: write the numbers from the client',
    'quotes': 'nothing to do',
    'text-indent': 'use padding-left on the block',
    'word-spacing': 'RmlUi has no word-spacing',
    'text-underline-offset': 'nothing to do',
    'text-decoration-color': 'RmlUi draws the decoration in the text colour',
    'text-decoration-thickness': 'nothing to do',
    'text-decoration-style': 'nothing to do',
    'font-variant': 'nothing to do',
    'font-variant-numeric': 'use a font with tabular figures',
    'font-feature-settings': 'nothing to do',
    'font-stretch': 'load the condensed/expanded face as its own family',
    'font-display': 'nothing to do',
    'hyphens': 'nothing to do',
    'tab-size': 'nothing to do',
    'unicode-bidi': 'nothing to do',
    'writing-mode': 'RmlUi lays out horizontal text only',
    'columns': 'split the content into flex columns',
    'column-count': 'split the content into flex columns',
    'column-width': 'split the content into flex columns',
    'table-layout': 'size the cells yourself',
    'border-collapse': 'RmlUi tables have no border collapsing: put borders on the cells',
    'border-spacing': 'use cell padding or margins',
    'empty-cells': 'nothing to do',
    'caption-side': 'nothing to do',
    'accent-color': 'nothing to do',
    'scrollbar-width': 'style the RmlUi <scrollbarvertical> element instead',
    'scrollbar-color': 'style the RmlUi <scrollbarvertical> element instead',
    'scrollbar-gutter': 'nothing to do',
    'overscroll-behavior-x': 'use overscroll-behavior',
    'overscroll-behavior-y': 'use overscroll-behavior',
    'scroll-snap-type': 'RmlUi has no scroll snapping',
    'scroll-snap-align': 'RmlUi has no scroll snapping',
    'scroll-margin': 'nothing to do',
    'scroll-padding': 'nothing to do',
    'backface-visibility': 'RmlUi draws back faces',
    'transform-style': 'RmlUi flattens 3D children; transform each element itself',
    'translate': 'write it into transform: translate(...)',
    'rotate': 'write it into transform: rotate(...)',
    'scale': 'write it into transform: scale(...)',
    'clip-path': 'use mask-image with an image or a gradient',
    'shape-outside': 'nothing to do',
    'filter-function': 'nothing to do',
    'box-decoration-break': 'nothing to do',
    'print-color-adjust': 'nothing to do',
    'color-scheme': 'nothing to do',
    'forced-color-adjust': 'nothing to do',
    'speak': 'nothing to do',
    'animation-name': 'write the animation shorthand (RmlUi has no animation longhands)',
    'animation-duration': 'write the animation shorthand (RmlUi has no animation longhands)',
    'animation-timing-function': 'write the animation shorthand (RmlUi has no animation longhands)',
    'animation-delay': 'write the animation shorthand (RmlUi has no animation longhands)',
    'animation-iteration-count': 'write the animation shorthand (RmlUi has no animation longhands)',
    'animation-direction': 'write the animation shorthand (RmlUi has no animation longhands)',
    'animation-fill-mode': 'RmlUi has no fill modes',
    'animation-play-state': 'write paused into the animation shorthand, or stop it from the client',
    'transition-property': 'write the transition shorthand (RmlUi has no transition longhands)',
    'transition-duration': 'write the transition shorthand (RmlUi has no transition longhands)',
    'transition-timing-function': 'write the transition shorthand (RmlUi has no transition longhands)',
    'transition-delay': 'write the transition shorthand (RmlUi has no transition longhands)',
    'text-shadow-color': 'nothing to do',
    'grid': 'RmlUi has no grid: use flex rows/columns',
    'container-type': 'RmlUi has no container queries: the converter folds cq* units with this container\'s size',
    'container-name': 'RmlUi has no container queries',
    'container': 'RmlUi has no container queries: the converter folds cq* units with the container\'s size',
}
GRID_PROPS = ('grid-template', 'grid-template-columns', 'grid-template-rows', 'grid-template-areas', 'grid-area',
              'grid-column', 'grid-row', 'grid-column-start', 'grid-column-end', 'grid-row-start', 'grid-row-end',
              'grid-auto-flow', 'grid-auto-columns', 'grid-auto-rows', 'place-items', 'place-content')
for _g in GRID_PROPS:
    UNSUPPORTED.setdefault(_g, 'RmlUi has no grid: use flex rows/columns with widths')

FONT_SIZE_KW = {'xx-small': 9, 'x-small': 10, 'small': 13, 'medium': 16, 'large': 18, 'x-large': 24, 'xx-large': 32,
                'xxx-large': 48}
BORDER_KW = {'thin': 1, 'medium': 3, 'thick': 5}
GENERIC_FAMILIES = {'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-sans-serif',
                    'ui-serif', 'ui-monospace', 'ui-rounded', 'math', 'emoji', 'fangsong'}


class Ctx:
    """what a declaration needs from its rule and the run"""
    def __init__(self, units, lookup, asset, rule_decls=None, keyframes=(), where=''):
        self.units, self.lookup, self.asset = units, lookup, asset
        self.rule_decls = rule_decls or {}
        self.keyframes, self.where = keyframes, where
        self.color = None
        self.used_color = False   # a handler fell back to the text colour (a colourless border or shadow)


def prepare(name, value, ctx, issues):
    """var/units/calc/colours folded -> tokens"""
    toks = V.tokenize(value)
    toks = V.resolve_vars(toks, ctx.lookup)
    notes = []
    toks = V.convert_units(toks, ctx.units, notes)
    for u in sorted(set(notes)):
        if u == 'fr':
            continue
        raise ValueIssue(f'unit {u}', {'ch': 'about 0.5em per character in most fonts: write dp',
                                       'ex': 'about 0.5em: write dp or em'}.get(
            u, 'the query container has no fixed size (or the elements have containers of different sizes): write '
               'dp' if u.startswith('cq') else 'write the value in dp'))
    toks = V.fold_math(toks)
    if name not in NO_COLOR_PROPS:
        toks = V.convert_colors(toks, ctx.color)
    return V.strip_ws(toks)


# ---- background / mask layers
def _layer(words, issues, what):
    """one comma layer of background or mask -> dict(image, color, size, pos, repeat, other)"""
    L = {'image': None, 'color': None, 'size': None, 'pos': [], 'repeat': None, 'other': []}
    after_slash = False
    for w in words:
        t = w[0] if len(w) == 1 else None
        if t and t[0] == 'slash':
            after_slash = True
            continue
        if t and (t[0] == 'url' or (t[0] == 'func' and t[1].endswith('gradient'))):
            L['image'] = t
        elif t and t[0] == 'func' and t[1] in ('image-set', '-webkit-image-set', 'element', 'cross-fade', 'paint'):
            L['other'].append(V.ser(w))
        elif t and (t[0] == 'hash' or (t[0] == 'ident' and t[1] == 'transparent')):
            L['color'] = t[1]
        elif t and t[0] == 'ident' and t[1] == 'none':
            L['image'] = ('none',)
        elif t and t[0] == 'ident' and t[1] in ('repeat', 'no-repeat', 'repeat-x', 'repeat-y', 'space', 'round'):
            L['repeat'] = (L['repeat'] or []) + [t[1]]
        elif t and t[0] == 'ident' and t[1] in ('scroll', 'fixed', 'local', 'border-box', 'padding-box',
                                               'content-box', 'text', 'add', 'subtract', 'intersect', 'exclude',
                                               'alpha', 'luminance', 'match-source'):
            L['other'].append(t[1])
        elif after_slash:
            L['size'] = (L['size'] or []) + [V.ser([x]) if x[0] != 'num' else len_str(x) for x in w]
        else:
            L['pos'] += [V.ser([x]) if x[0] != 'num' else len_str(x) for x in w]
    return L


def _size_fit(size):
    """background-size words -> RmlUi image fit, or None when it has none"""
    if size is None:
        return 'auto'
    s = ' '.join(size)
    if s in ('contain', 'cover'):
        return s
    if s in ('100% 100%',):
        return 'fill'
    if s in ('auto', 'auto auto'):
        return 'auto'
    return None


def _align(pos, issues, what):
    """background-position words -> RmlUi image alignment words (x then y), None when it can't be written. RmlUi's
    image decorator takes keywords, % or px here, not dp (DecoratorTiled.cpp): a dp length is written in px"""
    if not pos:
        return []
    kw = {'left': 'x', 'right': 'x', 'top': 'y', 'bottom': 'y', 'center': None}
    pos = position2(pos, issues, what)
    if pos is None:
        return None
    if len(pos) == 1:
        pos = pos + ['center']
    x, y = pos
    if kw.get(x) == 'y' or kw.get(y) == 'x':
        x, y = y, x
    mapx = {'0': 'left', '0%': 'left', '50%': 'center', '100%': 'right'}
    mapy = {'0': 'top', '0%': 'top', '50%': 'center', '100%': 'bottom'}
    x, y = mapx.get(x, x), mapy.get(y, y)
    px = [v for v in (x, y) if v.endswith('dp')]
    if px:
        issues.append(Issue(f'{what} position {" ".join(px)}', 'RmlUi\'s image alignment takes px or %, not dp: '
                            'written in px (the same at a dp ratio of 1; give it in % to scale)'))
        x, y = [v[:-2] + 'px' if v.endswith('dp') else v for v in (x, y)]
    return [x, y]


def _tiling(rep, issues, what):
    """background-repeat words -> RmlUi's fit for an image at natural size: repeat, repeat-x, repeat-y or scale-none"""
    words = rep or ['repeat']
    if len(words) == 1:
        w = words[0]
        xy = {'repeat-x': ('repeat', 'no-repeat'), 'repeat-y': ('no-repeat', 'repeat')}.get(w, (w, w))
    else:
        xy = tuple(words[:2])
    if any(w in ('space', 'round') for w in xy):
        issues.append(Issue(f'{what} repeat {" ".join(words)}', 'RmlUi tiles at the natural size: written as repeat'))
        xy = tuple('repeat' if w in ('space', 'round') else w for w in xy)
    return {('repeat', 'repeat'): 'repeat', ('repeat', 'no-repeat'): 'repeat-x',
            ('no-repeat', 'repeat'): 'repeat-y'}.get(xy, 'scale-none')


def _quote_path(src):
    return '"%s"' % src.replace('"', '%22') if re.search(r'[\s()\'",]', src) else src


def image_decorator(L, ctx, issues, what):
    """a layer's image -> RCSS decorator text (or None)"""
    img = L['image']
    if img is None or img == ('none',):
        return None
    if img[0] == 'url':
        src = ctx.asset(img[1], issues)
        if src is None:
            return None
        if re.search(r'[;{}]', src):
            issues.append(Issue(f'{what} image {img[1]}', 'RmlUi\'s sheet parser ends a declaration at ; { or } even '
                                'inside quotes: rename the file (dropped)'))
            return None
        fit = _size_fit(L['size'])
        al = _align(L['pos'], issues, what)
        parts = [_quote_path(src)]
        if fit is None:
            issues.append(Issue(f'{what} size {" ".join(L["size"])}',
                                'RmlUi\'s image decorator fills, contains or covers its box: written as fill; size '
                                'the element to the image instead'))
            fit = 'fill'
        if fit == 'auto':
            fit = _tiling(L['repeat'], issues, what)
            if not al and al is not None:
                al = ['left', 'top']
        if fit != 'fill':
            parts.append(fit)
        if al and fit != 'fill' and al != ['center', 'center']:   # (a position it can't read: reported, centred)
            parts += al
        return 'image(%s)' % ' '.join(parts)
    return _tiled_gradient(img, L, issues, what)


FILL_SIZES = ('auto', 'auto auto', '100% 100%')
ORIGIN_POS = ('', '0 0', '0% 0%', 'left top', 'top left', '0')


def _stops_at(stops, per):
    """gradient stops (token lists) -> [(colour, offset in dp)] on a tile of `per` dp, None when one can't be placed"""
    out = []
    for k, st in enumerate(stops):
        ws = V.words(V.strip_ws(st))
        col = [w for w in ws if V.is_color(w[0])]
        at = [w[0] for w in ws if not V.is_color(w[0])]
        if len(col) != 1 or len(at) > 2:
            return None
        for t in at or [None]:
            if t is None:
                v = 0 if k == 0 else per if k == len(stops) - 1 else None
            elif t[0] == 'num' and t[2] == '%':
                v = per * t[1] / 100
            elif t[0] == 'num' and (t[2] == 'dp' or (t[2] == '' and t[1] == 0)):
                v = t[1]
            else:
                v = None
            if v is None:
                return None
            out.append((V.ser(col[0]), v))
    return out


def _tiled_gradient(img, L, issues, what):
    """a gradient layer: CSS sizes, places and tiles it like an image; RmlUi's gradient decorators fill the box. A
    linear gradient across an axis, tiled along that axis from the origin, is a repeating gradient with the tile as its
    period (the stripe/grid idiom); any other size or position is reported"""
    size = ' '.join(L['size'] or ['auto'])
    pos = ' '.join(L['pos'] or [])
    if size in FILL_SIZES:   # a gradient at auto size fills its box: no position or tiling shows
        return gradient(img, issues)
    name, parts = img[1], V.split(img[2])
    p0 = V.strip_ws(parts[0])
    has_dir = not any(V.is_color(w[0]) for w in V.words(p0))
    first = V.ser(p0) if has_dir else 'to bottom'
    axis = {'90deg': 0, 'to right': 0, '180deg': 1, 'to bottom': 1}.get(first)
    if name == 'linear-gradient' and axis is not None and pos in ORIGIN_POS:
        sz = list(L['size'] or []) + ['auto', 'auto']
        period = sz[axis]
        tiles = _tiling(L['repeat'], [], what) in ('repeat', ('repeat-x', 'repeat-y')[axis])
        if period.endswith('dp') and tiles:
            per = float(period[:-2])
            out = _stops_at(parts[1:] if has_dir else parts, per)
            if out:
                if out[0][1] > 0:
                    out.insert(0, (out[0][0], 0))   # a repeating gradient's period runs from its first stop
                if out[-1][1] < per:
                    out.append((out[-1][0], per))
                text = ', '.join(([first] if has_dir else []) + [f'{c} {V.fmt(v)}dp' for c, v in out])
                return 'repeating-' + gradient(('func', 'linear-gradient', V.tokenize(text)), issues)
    issues.append(Issue(f'{what} {name}() sized {size}' + (f' at {pos}' if pos else ''),
                        'RmlUi\'s gradient decorators fill the box: written filling it (give the gradient an element '
                        'of that size and place, or use a repeating gradient)'))
    return gradient(img, issues)


POS_KW = {'left': 'x', 'right': 'x', 'top': 'y', 'bottom': 'y', 'center': None}
RADIAL_SIZE_KW = {'closest-side', 'closest-corner', 'farthest-side', 'farthest-corner'}


def position2(words, issues, what):
    """a CSS <position> (1-4 words, as strings) -> [x, y] the two-value form RmlUi takes. An offset from left/top is
    the plain length; an offset from right/bottom in % becomes its complement; one in a length can't be written in two
    values: reported, kept as the edge keyword"""
    if len(words) <= 2:
        return list(words)
    x = y = None
    i = 0
    while i < len(words):
        w = words[i]
        off = words[i + 1] if i + 1 < len(words) and words[i + 1] not in POS_KW else None
        axis = POS_KW.get(w, 'bad')
        if axis == 'bad':
            issues.append(Issue(f'{what} position {" ".join(words)}', 'RmlUi aligns with two values (x y): centred '
                            'instead; write it as two values'))
            return None
        if axis is None:
            val = 'center'
        elif off is None:
            val = w
        elif w in ('left', 'top'):
            val = off
        elif off.endswith('%'):
            val = V.fmt(100 - float(off[:-1])) + '%'
        else:
            issues.append(Issue(f'{what} position {" ".join(words)}', f'RmlUi takes two values (x y): an offset from '
                                f'{w} needs the box size; written as {w}, give the offset as a % or from left/top'))
            val = w
        if axis == 'y' or (axis is None and x is not None):
            y = val
        else:
            x = val
        i += 2 if off is not None else 1
    return [x or 'center', y or 'center']


def _gradient_prelude(name, p, issues):
    """the first argument of a gradient (direction, shape, size, position, colour space) in the order RmlUi parses:
    shape before size, `at` two-value position; `in <space>` is dropped (RmlUi interpolates in sRGB)"""
    words = [V.ser(w) for w in V.words(p)]
    if 'in' in words:
        k = words.index('in')
        end = k + 2
        if end < len(words) and words[end] in ('shorter', 'longer', 'increasing', 'decreasing'):
            end += 2   # `longer hue`
        issues.append(Issue(f'{name}() interpolation {" ".join(words[k:end])}', 'RmlUi interpolates gradients in '
                            'sRGB: dropped (colours between the stops may differ)'))
        words = words[:k] + words[end:]
    pos = []
    if 'at' in words:
        k = words.index('at')
        pos = position2(words[k + 1:], issues, f'{name}()')
        words = words[:k]
        if pos is None:
            pos = ['center', 'center']
    if 'radial' in name:
        shape = [w for w in words if w in ('circle', 'ellipse')]
        size = [w for w in words if w not in ('circle', 'ellipse')]
        words = shape + size
    return ' '.join(words + (['at'] + pos if pos else []))


def gradient(t, issues):
    """a CSS gradient function token -> RmlUi decorator text"""
    name, args = t[1], t[2]
    parts = V.split(args)
    legacy = re.match(r'^-(webkit|moz|o)-', name)
    if legacy:   # the prefixed form: the direction names the start side, angles run counter-clockwise from east
        name = name[legacy.end():]
        if 'linear' not in name:
            raise ValueIssue(f'-{legacy.group(1)}-{name}()', f'the prefixed form has its own syntax: write {name}()')
        ws0 = [V.ser(w) for w in V.words(V.strip_ws(parts[0]))]
        opp = {'left': 'right', 'right': 'left', 'top': 'bottom', 'bottom': 'top'}
        if ws0 and all(w in opp for w in ws0):
            parts = [[('ident', 'to'), ('ws',)] + [x for w in ws0 for x in (('ident', opp[w]), ('ws',))][:-1]] + parts[1:]
        elif len(ws0) == 1 and re.fullmatch(r'-?[\d.]+deg', ws0[0]):
            parts = [[('num', 90 - float(ws0[0][:-3]), 'deg')]] + parts[1:]
    out = []
    conic = 'conic' in name
    for k, p in enumerate(parts):
        p = V.strip_ws(p)
        ws = V.words(p)
        if not ws:
            continue
        if k == 0 and not any(V.is_color(w[0]) for w in ws):
            pre = _gradient_prelude(name, p, issues)
            if pre:
                out.append(pre)
            continue
        colors = [w for w in ws if V.is_color(w[0])]
        if not colors:
            raise ValueIssue(f'{name}() colour hint {V.ser(p)!r}', 'RmlUi stops need a colour each: write the '
                             'midpoint as its own stop')
        poss = [w for w in ws if not V.is_color(w[0])]
        col = V.ser(colors[0])
        if not poss:
            out.append(col)
        for w in poss:   # a double position `#c 0 1px` is written as two stops (same gradient)
            x = w[0]
            if x[0] == 'num' and x[1] == 0 and x[2] == '':
                out.append(col + (' 0deg' if conic else ' 0dp'))
            else:
                out.append(col + ' ' + V.ser(w))
    # `transparent` next to a colour: written as that colour at zero alpha (what CSS's premultiplied interpolation,
    # and RmlUi's, make of it anyway; readable, and rml-preview paints it)
    for i in range(len(out)):
        if out[i].startswith('transparent'):
            near = [out[j].split()[0] for j in list(range(i - 1, -1, -1)) + list(range(i + 1, len(out)))
                    if out[j].startswith('#')]
            if near:
                h = near[0][1:]
                h = ''.join(c * 2 for c in h[:3]) if len(h) in (3, 4) else h[:6]
                out[i] = '#' + h + '00' + out[i][len('transparent'):]
    return '%s(%s)' % (name, ', '.join(out))


def map_layers(prop, decls, ctx, issues, sheet, defaults=None):
    """the rule's background*/mask* declarations in order -> RCSS declarations"""
    is_mask = prop == 'mask'
    state = {'color': None, 'layers': None, 'color_set': False, 'image_set': False}
    longs = {}
    for d in decls:
        n = d.name
        base = n.replace('-webkit-', '')
        if base in ('background', 'mask'):
            layers = [_layer(V.words(V.strip_ws(p)), issues, base) for p in V.split(d.toks)]
            state['layers'] = layers
            state['color'] = layers[-1]['color'] if not is_mask else None
            state['color_set'] = state['image_set'] = True
            longs = {}
            for L in layers:
                if L['other']:
                    issues.append(Issue(f'{base} {", ".join(L["other"])}', 'RmlUi paints the border box: dropped'))
            if is_mask and layers[-1]['color']:
                issues.append(Issue('mask colour', 'dropped (a mask is the image alpha)'))
        elif base in ('background-color',):
            state['color'] = V.ser(d.toks)
            state['color_set'] = True
        elif base in ('background-image', 'mask-image'):
            imgs = [_layer(V.words(V.strip_ws(p)), issues, base) for p in V.split(d.toks)]
            state['layers'] = imgs
            state['image_set'] = True
        else:
            longs[base] = d.toks
    layers = state['layers'] or []
    for L in layers:   # the cascade winners for size/position/repeat over every rule matching these elements
        for k, v in (defaults or {}).items():
            if not k.startswith('_'):
                L[k] = list(v) if v is not None else None
    for key, field in (('size', 'size'), ('position', 'pos'), ('repeat', 'repeat')):
        lk = ('mask-' if is_mask else 'background-') + key
        if lk in longs:
            vals = [V.words(V.strip_ws(p)) for p in V.split(longs.pop(lk))]
            if not layers and not (defaults or {}).get('_image'):
                issues.append(Issue(f'{lk} where no rule sets an image', 'dropped'))
            for i, L in enumerate(layers):
                if defaults and field in defaults:
                    continue   # the cascade already decided
                w = vals[min(i, len(vals) - 1)]
                L[field] = [V.ser([x]) if x[0] != 'num' else len_str(x) for ww in w for x in ww]
    for lk in longs:
        issues.append(Issue(f'{lk}', 'RmlUi has no %s: dropped' % lk))
    out = []
    if not is_mask and state['color_set'] and (state['color'] or sheet.get('background-color')):
        out.append(('background-color', state['color'] or 'transparent'))
    if state['image_set'] or layers:
        decos, failed = [], False
        for L in layers:
            try:
                d = image_decorator(L, ctx, issues, prop)
            except ValueIssue as e:
                issues.append(Issue(e.what, e.todo))
                d, failed = None, True
            if d:
                decos.append(d)
        target = 'mask-image' if is_mask else 'decorator'
        if failed:
            pass   # an invalid value is dropped whole, as a browser does: an image from another rule stays
        elif decos:
            out.append((target, ', '.join(decos)))
        elif state['image_set'] and sheet.get(target):
            out.append((target, 'none'))
    elif not is_mask and state['color_set'] and sheet.get('decorator') and any(
            d.name == 'background' for d in decls):
        out.append(('decorator', 'none'))   # the shorthand clears an image another rule may set
    return out


# ---- single declarations
def map_decl(d, ctx, issues):
    """d has .name and .toks (prepared). Returns [(name, value)]"""
    n, toks = d.name, d.toks
    s = V.ser(toks)
    ws = V.words(toks)
    first = ws[0][0] if ws and len(ws[0]) == 1 else None
    if first and first[0] == 'ident' and first[1].lower() in GLOBAL_KW and len(ws) == 1:
        issues.append(Issue(f'{n}: {first[1]}', 'RmlUi has no %s: write the value (inherited properties inherit '
                            'anyway)' % first[1]))
        return []
    for pre in ('-webkit-', '-moz-', '-ms-', '-o-'):
        if n.startswith(pre):
            issues.append(Issue(f'{n}', f'vendor prefix dropped' + (
                f'; RmlUi has {n[len(pre):]}' if n[len(pre):] in PROPERTIES or n[len(pre):] in SHORTHANDS
                else '')))
            return []
    h = HANDLERS.get(n)
    kinds, kws = PROPERTIES.get(n, ((), ()))
    if kws and any(t[0] == 'ident' and t[1] != t[1].lower() for t in toks):
        # CSS keywords are case-insensitive, RmlUi's are lower-case: DISPLAY: FLEX is display: flex
        toks = [('ident', t[1].lower()) if t[0] == 'ident' and (not kinds or t[1].lower() in kws) else t for t in toks]
        s, ws = V.ser(toks), V.words(toks)
    if h:
        return h(n, toks, ws, s, ctx, issues)
    if n in OPEN77_PROPS:
        return [(n, s)]
    if n in UNSUPPORTED:
        issues.append(Issue(f'{n}: {s}', UNSUPPORTED[n]))
        return []
    if n in PROPERTIES:
        return check_keywords(n, s, ws, issues)
    if n in COLOUR_SHORTHANDS:
        return check_keywords(n, s, ws, issues)
    if n in SHORTHANDS:
        return [(n, s)]
    issues.append(Issue(f'{n}: {s}', 'RmlUi 6.3 has no %s property' % n))
    return []


COLOUR_SHORTHANDS = {'border-color'}


def check_keywords(n, s, ws, issues):
    kinds, kws = PROPERTIES[n] if n in PROPERTIES else (('color',), ())
    if 'color' in kinds:   # a name the colour table does not know (CSS system colours, typos): RmlUi refuses it
        bad = [t[1] for w in ws for t in w if t[0] == 'ident' and t[1].lower() not in tuple(kws or ()) + ('transparent',)
               and not V.is_color(t)]
        if bad:
            issues.append(Issue(f'{n}: {s}', f'RmlUi has no colour named {bad[0]}: write the colour as hex'))
            return []
    if len(ws) == 1 and len(ws[0]) == 1 and ws[0][0][0] == 'ident' and 'string' not in kinds and kws is not None:
        if ws[0][0][1] not in kws and not (kinds and ws[0][0][1] in ('transparent',) and 'color' in kinds):
            if 'color' in kinds or 'transform' in kinds or 'filter' in kinds or 'box_shadow' in kinds \
                    or 'decorator' in kinds:
                return [(n, s)]
            issues.append(Issue(f'{n}: {s}', 'RmlUi accepts %s' % (', '.join(kws) if kws else 'a %s' % '/'.join(kinds))))
            return []
    return [(n, s)]


def h_display(n, toks, ws, s, ctx, issues):
    v = s.lower()
    if v == 'list-item':
        return [('display', 'block')]
    if v in ('grid', 'inline-grid'):
        return [('display', '__grid__' if v == 'grid' else '__inline-grid__')]   # resolved by the rule pass
    if v == 'contents':
        issues.append(Issue('display: contents', 'RmlUi has no contents boxes: move the children up in the markup'))
        return []
    if v in ('block flex', 'flex block'):
        return [('display', 'flex')]
    if v in ('inline flex', 'flex inline'):
        return [('display', 'inline-flex')]
    return check_keywords(n, s, ws, issues)


def h_position(n, toks, ws, s, ctx, issues):
    if s == 'sticky' or s == '-webkit-sticky':
        issues.append(Issue('position: sticky', 'RmlUi has no sticky positioning: written as relative'))
        return [('position', 'relative')]
    return check_keywords(n, s, ws, issues)


def h_overflow(n, toks, ws, s, ctx, issues):
    m = {'clip': 'hidden', 'overlay': 'auto'}
    return [(n, ' '.join(m.get(w[0][1], w[0][1]) if w[0][0] == 'ident' else V.ser(w) for w in ws))]


def h_visibility(n, toks, ws, s, ctx, issues):
    return [(n, 'hidden' if s == 'collapse' else s)]


def h_opacity(n, toks, ws, s, ctx, issues):
    t = toks[0] if toks else None
    if t and t[0] == 'num' and t[2] == '%':
        return [(n, V.fmt(t[1] / 100))]
    return [(n, s)]


def h_size(n, toks, ws, s, ctx, issues):
    if s in ('fit-content', 'min-content', 'max-content', 'stretch', '-webkit-fill-available', '-moz-available') \
            or s.startswith('fit-content('):
        issues.append(Issue(f'{n}: {s}', 'RmlUi has no intrinsic sizing keywords: auto (shrink-to-fit for '
                            'absolute/inline-block/flex items) or a dp value'))
        return []
    return check_keywords(n, s, ws, issues)


def h_align(n, toks, ws, s, ctx, issues):
    words = [w[0][1] for w in ws if w[0][0] == 'ident' and w[0][1] not in ('safe', 'unsafe')]
    v = ' '.join(words)
    m = {'start': 'flex-start', 'end': 'flex-end', 'self-start': 'flex-start', 'self-end': 'flex-end',
         'left': 'flex-start', 'right': 'flex-end'}
    if v == 'normal':
        v = 'stretch' if n != 'justify-content' else 'flex-start'
    v = m.get(v, v)
    if n == 'justify-content' and v == 'stretch':
        v = 'flex-start'
    return check_keywords(n, v, [[('ident', v)]], issues)


def h_text_align(n, toks, ws, s, ctx, issues):
    m = {'start': 'left', 'end': 'right', '-webkit-center': 'center', '-moz-center': 'center'}
    if s == 'match-parent':
        issues.append(Issue('text-align: match-parent', 'dropped (inherits anyway)'))
        return []
    return check_keywords(n, m.get(s, s), [[('ident', m.get(s, s))]], issues)


def h_white_space(n, toks, ws, s, ctx, issues):
    if s == 'break-spaces':
        issues.append(Issue('white-space: break-spaces', 'written as pre-wrap'))
        return [(n, 'pre-wrap')]
    if s in ('nowrap', 'pre', 'pre-wrap', 'pre-line', 'normal'):
        return [(n, s)]
    if s in ('collapse', 'preserve nowrap'):
        return [(n, 'nowrap' if 'nowrap' in s else 'normal')]
    return check_keywords(n, s, ws, issues)


def h_overflow_wrap(n, toks, ws, s, ctx, issues):
    if s in ('anywhere', 'break-word'):
        return [('word-break', 'break-word')]
    if s == 'normal':
        return []
    return check_keywords('word-break', s, ws, issues)


def h_word_break(n, toks, ws, s, ctx, issues):
    if s == 'keep-all':
        issues.append(Issue('word-break: keep-all', 'written as normal'))
        return [(n, 'normal')]
    return check_keywords(n, s, ws, issues)


def h_font_family(n, toks, ws, s, ctx, issues):
    fams = []
    for p in V.split(toks):
        p = V.strip_ws(p)
        if not p:
            continue
        if len(p) == 1 and p[0][0] == 'str':
            fams.append(p[0][1])
        else:
            fams.append(' '.join(x[1] for x in p if x[0] == 'ident'))
    if not fams:
        return []
    keep = fams[0]
    if keep.lower() in GENERIC_FAMILIES:
        issues.append(Issue(f'font-family: {s}', 'RmlUi has no generic families: load a font with '
                            'Open77.ui.loadFont(path, family) and name that family here'))
        return []
    if [f for f in fams[1:] if f.lower() not in GENERIC_FAMILIES]:
        issues.append(Issue(f'font-family fallbacks {", ".join(f for f in fams[1:] if f.lower() not in GENERIC_FAMILIES)}',
                            f'RmlUi takes one family: kept {keep} (load it with Open77.ui.loadFont)'))
    return [('font-family', keep)]


def h_font_weight(n, toks, ws, s, ctx, issues):
    if s in ('lighter', 'bolder'):
        issues.append(Issue(f'font-weight: {s}', 'write the weight number'))
        return []
    return [(n, s)]


def h_font_size(n, toks, ws, s, ctx, issues):
    if s in FONT_SIZE_KW:
        return [(n, V.fmt(FONT_SIZE_KW[s] / ctx.units.ppd) + 'dp')]
    if s == 'smaller':
        return [(n, '0.833em')]
    if s == 'larger':
        return [(n, '1.2em')]
    return [(n, s)]


def h_line_height(n, toks, ws, s, ctx, issues):
    return [(n, '1.2' if s == 'normal' else s)]


def h_font(n, toks, ws, s, ctx, issues):
    if len(ws) == 1 and ws[0][0][0] == 'ident' and ws[0][0][1] in ('caption', 'icon', 'menu', 'message-box',
                                                                    'small-caption', 'status-bar'):
        issues.append(Issue(f'font: {s}', 'write the font properties'))
        return []
    style, weight, size, lh, fam = 'normal', '400', None, '1.2', None
    i = 0
    flat = ws
    while i < len(flat):
        w = flat[i]
        t = w[0]
        if t[0] == 'ident' and t[1] in ('italic', 'oblique'):
            style = 'italic'
        elif t[0] == 'ident' and t[1] in ('normal',):
            pass
        elif t[0] == 'ident' and t[1] in ('bold', 'bolder', 'lighter'):
            weight = {'bold': '700'}.get(t[1], t[1])
            if t[1] != 'bold':
                issues.append(Issue(f'font weight {t[1]}', 'written as 400; write the number'))
                weight = '400'
        elif t[0] == 'ident' and t[1] in ('small-caps',) or (t[0] == 'ident' and t[1].endswith('condensed')) \
                or (t[0] == 'ident' and t[1].endswith('expanded')):
            issues.append(Issue(f'font {t[1]}', 'dropped'))
        elif t[0] == 'num' and t[2] == '' and size is None and 1 <= t[1] <= 1000:
            weight = V.fmt(t[1])
        elif size is None and (t[0] == 'num' or (t[0] == 'ident' and t[1] in FONT_SIZE_KW)):
            size = V.ser(w)
            if t[0] == 'ident':
                size = V.fmt(FONT_SIZE_KW[t[1]] / ctx.units.ppd) + 'dp'
            if i + 2 < len(flat) and flat[i + 1][0][0] == 'slash':
                lh = V.ser(flat[i + 2])
                lh = '1.2' if lh == 'normal' else lh
                i += 2
        elif size is not None:
            rest = []
            for ww in flat[i:]:
                rest.extend(ww)
                rest.append(('ws',))
            fam = h_font_family('font-family', V.strip_ws(rest), None, V.ser(rest), ctx, issues)
            break
        i += 1
    if size is None:
        issues.append(Issue(f'font: {s}', 'could not read a size: write the longhands'))
        return []
    out = [('font-style', style), ('font-weight', weight), ('font-size', size), ('line-height', lh)]
    if fam:
        out += fam
    return out


def h_border(n, toks, ws, s, ctx, issues):
    width = color = None
    style = None
    for w in ws:
        t = w[0]
        if t[0] == 'num':
            width = len_str(t)
        elif t[0] == 'ident' and t[1] in BORDER_KW:
            width = V.fmt(BORDER_KW[t[1]] / ctx.units.ppd) + 'dp'
        elif t[0] == 'ident' and t[1] in ('none', 'hidden', 'solid', 'dashed', 'dotted', 'double', 'groove',
                                          'ridge', 'inset', 'outset'):
            style = t[1]
        elif V.is_color(t) or t[0] == 'hash':
            color = V.ser(w)
        else:
            issues.append(Issue(f'{n}: {s}', 'could not read it: write width and colour'))
            return []
    side = n[len('border'):]   # '', '-top', ...
    if style in ('none', 'hidden') or (style is None and width is None and color is None) or width in ('0', '0dp'):
        return [(f'border{side}-width' if side else 'border-width', '0')]
    if style not in (None, 'solid'):
        issues.append(Issue(f'border style {style}', 'RmlUi draws solid borders only: written solid'))
    if width is None:
        width = V.fmt(3 / ctx.units.ppd) + 'dp'   # CSS medium
    if color is None:
        if ctx.color:
            color, ctx.used_color = ctx.color, True
        else:
            issues.append(Issue(f'{n}: {s} without a colour', 'CSS uses the text colour, RmlUi black: write the '
                                'colour'))
            return [(f'border{side}-width' if side else 'border-width', width)]
    return [(n, f'{width} {color}')]


def h_border_style(n, toks, ws, s, ctx, issues):
    if all(w[0][0] == 'ident' and w[0][1] == 'solid' for w in ws):
        return []   # RmlUi borders are solid
    if all(w[0][0] == 'ident' and w[0][1] in ('none', 'hidden') for w in ws):
        side = n[len('border'):-len('-style')]
        return [(f'border{side}-width', '0')]
    issues.append(Issue(f'{n}: {s}', 'RmlUi draws solid borders only (none = border-width: 0)'))
    return []


def h_border_width(n, toks, ws, s, ctx, issues):
    vals = []
    for w in ws:
        t = w[0]
        if t[0] == 'ident' and t[1] in BORDER_KW:
            vals.append(V.fmt(BORDER_KW[t[1]] / ctx.units.ppd) + 'dp')
        else:
            vals.append(len_str(t) if t[0] == 'num' else V.ser(w))
    return [(n, ' '.join(vals))]


def h_radius(n, toks, ws, s, ctx, issues):
    if any(w[0][0] == 'slash' for w in ws):
        k = [i for i, w in enumerate(ws) if w[0][0] == 'slash'][0]
        issues.append(Issue(f'{n}: {s}', 'RmlUi has circular corners only: kept the first radii'))
        ws = ws[:k]
    out = []
    for w in ws:
        t = w[0]
        if t[0] == 'num' and t[2] == '%':
            wd, ht = ctx.rule_decls.get('width'), ctx.rule_decls.get('height')
            if wd and ht and wd == ht and wd.endswith('dp'):
                out.append(V.fmt(float(wd[:-2]) * t[1] / 100) + 'dp')
                continue
            issues.append(Issue(f'{n}: {s}', 'RmlUi radii take lengths, not %: write half the box size in dp '
                                '(the converter does it when the rule sets equal width and height)'))
            return []
        out.append(len_str(t) if t[0] == 'num' else V.ser(w))
    return [(n, ' '.join(out))]


def h_outline(n, toks, ws, s, ctx, issues):
    if s in ('none', '0', '0 none', 'none 0'):
        return []   # nothing drawn in CSS either
    issues.append(Issue(f'{n}: {s}', UNSUPPORTED['outline']))
    return []


def h_text_decoration(n, toks, ws, s, ctx, issues):
    lines = [w[0][1] for w in ws if w[0][0] == 'ident' and w[0][1] in ('none', 'underline', 'overline',
                                                                        'line-through')]
    if len(lines) != len(ws):
        issues.append(Issue(f'{n}: {s}', 'RmlUi takes one line keyword: kept %s' % (lines[0] if lines else 'none')))
    if len(lines) > 1:
        issues.append(Issue(f'{n}: {s}', 'RmlUi draws one decoration line: kept %s' % lines[0]))
    return [('text-decoration', lines[0] if lines else 'none')]


def _shadow_parts(p):
    lens, color, inset = [], None, False
    for w in V.words(V.strip_ws(p)):
        t = w[0]
        if t[0] == 'num':
            lens.append(len_str(t) if not (t[1] == 0 and t[2] == '') else '0dp')
        elif t[0] == 'ident' and t[1] == 'inset':
            inset = True
        else:
            color = V.ser(w)
    return lens, color, inset


def h_text_shadow(n, toks, ws, s, ctx, issues):
    if s == 'none':
        return [('font-effect', 'none')]
    effects = []
    for p in V.split(toks):
        lens, color, _ = _shadow_parts(p)
        if color is None and ctx.color:
            color, ctx.used_color = ctx.color, True
        if color is None or len(lens) < 2:
            issues.append(Issue(f'text-shadow: {s}', 'write offsets and a colour'))
            return []
        blur = lens[2] if len(lens) > 2 else '0dp'
        if blur in ('0', '0dp'):
            effects.append(f'shadow({lens[0]} {lens[1]} {color})')
        else:
            effects.append(f'glow(0dp {blur} {lens[0]} {lens[1]} {color})')
    return [('font-effect', ', '.join(effects))]


def h_box_shadow(n, toks, ws, s, ctx, issues):
    if s == 'none':
        return [(n, 'none')]
    out = []
    for p in V.split(toks):
        lens, color, inset = _shadow_parts(p)
        if color is None and ctx.color:
            color, ctx.used_color = ctx.color, True
        if color is None:
            issues.append(Issue(f'box-shadow: {s} without a colour', 'CSS uses the text colour: write the colour'))
            return []
        out.append(' '.join([color] + lens + (['inset'] if inset else [])))
    return [(n, ', '.join(out))]


def h_filter(n, toks, ws, s, ctx, issues):
    if s == 'none':
        return [(n, 'none')]
    out = []
    for w in ws:
        t = w[0]
        if t[0] == 'func' and t[1] == 'drop-shadow':
            lens, color, _ = _shadow_parts(t[2])
            if color is None and ctx.color:
                color, ctx.used_color = ctx.color, True
            if color is None:
                issues.append(Issue(f'{n}: drop-shadow without a colour', 'write the colour'))
                continue
            out.append('drop-shadow(%s)' % ' '.join([color] + lens))   # RmlUi: colour first
        elif t[0] == 'func' and t[1] in ('blur', 'brightness', 'contrast', 'grayscale', 'invert', 'opacity',
                                        'saturate', 'sepia', 'hue-rotate'):
            out.append(V.ser(w))
        elif t[0] == 'url':
            issues.append(Issue(f'{n}: url(...)', 'RmlUi has no SVG filters'))
        else:
            issues.append(Issue(f'{n}: {V.ser(w)}', 'RmlUi has no such filter'))
    return [(n, ' '.join(out))] if out else []


def h_transition(n, toks, ws, s, ctx, issues):
    if s in ('none', 'all 0s', '0s'):
        return [(n, 'none')]
    out = []
    items = V.split(toks)
    for k, p in enumerate(items):
        words = V.words(V.strip_ws(p))
        props, times, tween, named = [], [], None, False
        for w in words:
            if is_time(w):
                times.append(V.ser(w))
                continue
            tw = tween_of(w[0], issues)
            if tw:
                tween = tw
            elif w[0][0] == 'ident':
                named = True
                pn = w[0][1].lower()
                pn = {'background': 'background-color'}.get(pn, pn)
                if pn != 'all' and pn not in PROPERTIES and pn not in SHORTHANDS:
                    issues.append(Issue(f'transition of {pn}', 'RmlUi has no such property: dropped'))
                    continue
                props.append(pn)
        if not times or float(times[0][:-1]) == 0:
            if props:
                issues.append(Issue(f'transition {V.ser(p)} has no duration', 'dropped'))
            continue
        if named and not props:
            continue   # every property of this item was dropped: it must not turn into `all`
        if 'all' in (props or ['all']) and len(items) > 1:
            if k < len(items) - 1:
                issues.append(Issue(f'transition: {s}', 'RmlUi takes `all` only on its own: kept the `all` item; the '
                                    'other items\' timings are lost (write the properties instead of all)'))
            out = [' '.join(['all'] + times[:2] + [tween or EASE_MAP['ease']])]
            break
        out.append(' '.join((props or ['all']) + times[:2] + [tween or EASE_MAP['ease']]))
    return [(n, ', '.join(out))] if out else []


def h_animation(n, toks, ws, s, ctx, issues):
    if s == 'none':
        return [(n, 'none')]
    out = []
    for p in V.split(toks):
        words = V.words(V.strip_ws(p))
        times, tween, count, alt, paused, name = [], None, None, False, False, None
        for w in words:
            t = w[0]
            if is_time(w):
                times.append(V.ser(w))
            elif t[0] == 'num' and t[2] == '':
                if t[1] != int(t[1]):
                    issues.append(Issue(f'animation iteration count {V.fmt(t[1])}', 'RmlUi counts whole runs: '
                                        'rounded'))
                if round(t[1]) < 1:
                    issues.append(Issue(f'animation iteration count {V.fmt(t[1])}', 'RmlUi runs an animation at least '
                                        'once: dropped (leave the animation out instead)'))
                    count = '0'
                else:
                    count = str(int(round(t[1])))
            elif t[0] == 'ident' and t[1] == 'infinite':
                count = 'infinite'
            elif t[0] == 'ident' and t[1] == 'alternate':
                alt = True
            elif t[0] == 'ident' and t[1] in ('reverse', 'alternate-reverse'):
                issues.append(Issue(f'animation direction {t[1]}', 'RmlUi plays forwards (alternate works): '
                                    'reverse the keyframes'))
                alt = t[1] == 'alternate-reverse'
            elif t[0] == 'ident' and t[1] in ('forwards', 'backwards', 'both'):
                issues.append(Issue(f'animation fill-mode {t[1]}', 'RmlUi has no fill modes: check the end state '
                                    'in the game (set the final value as the element\'s own style)'))
            elif t[0] == 'ident' and t[1] in ('none', 'normal', 'running'):
                pass
            elif t[0] == 'ident' and t[1] == 'paused':
                paused = True
            else:
                tw = tween_of(t, issues)
                if tw:
                    tween = tw
                elif t[0] in ('ident', 'str'):
                    name = t[1]
        if name is None:
            issues.append(Issue(f'animation {V.ser(p)} names no keyframes', 'dropped'))
            continue
        if not times or float(times[0][:-1]) == 0:
            issues.append(Issue(f'animation {name} has no duration', 'dropped'))
            continue
        if count == '0':
            continue
        if ctx.keyframes and name not in ctx.keyframes:
            issues.append(Issue(f'animation {name}: no @keyframes {name} in the sheets', 'dropped'))
            continue
        parts = times[:2] + [tween or EASE_MAP['ease']]
        if count and count != '1':
            parts.append(count)
        if alt:
            parts.append('alternate')
        if paused:
            parts.append('paused')
        out.append(' '.join(parts + [name]))
    return [(n, ', '.join(out))] if out else []


TRANSFORM_FUNCS = {'translate', 'translatex', 'translatey', 'translatez', 'translate3d', 'rotate', 'rotatex', 'rotatey',
                   'rotatez', 'rotate3d', 'scale', 'scalex', 'scaley', 'scalez', 'scale3d', 'skew', 'skewx', 'skewy',
                   'matrix', 'matrix3d', 'perspective'}


def _transform_fn(t, issues, s):
    """one transform function in the forms RmlUi's parser takes (PropertyParserTransform.cpp): translate() and skew()
    with both arguments, scale*() with numbers (CSS allows %), an angle 0 with a unit"""
    name, args = t[1], [V.strip_ws(a) for a in V.split(t[2])]
    if name in ('scale', 'scalex', 'scaley', 'scalez', 'scale3d'):
        args = [[('num', a[0][1] / 100, '')] if len(a) == 1 and a[0][0] == 'num' and a[0][2] == '%' else a
                for a in args]
    if name == 'translate' and len(args) == 1:
        args.append([('num', 0, 'dp')])
    if name == 'skew' and len(args) == 1:
        args.append([('num', 0, 'deg')])
    if name.startswith(('rotate', 'skew')):
        args = [[('num', 0, 'deg')] if len(a) == 1 and a[0] == ('num', 0, '') and (name != 'rotate3d' or k == 3) else a
                for k, a in enumerate(args)]
    out = []
    for k, a in enumerate(args):
        if k:
            out.append(('comma',))
        out += a
    return (t[0], name, out)


def h_transform(n, toks, ws, s, ctx, issues):
    if s == 'none':
        return [(n, 'none')]
    out = []
    for t in [t for w in ws for t in w]:
        if t[0] != 'func' or t[1] not in TRANSFORM_FUNCS:
            issues.append(Issue(f'{n}: {s}', 'RmlUi has no %s: dropped' % V.ser([t])))
            return []
        out.append(V.ser([_transform_fn(t, issues, s)]))
    return [(n, ' '.join(out))]


def h_pointer_events(n, toks, ws, s, ctx, issues):
    return [(n, 'none' if s == 'none' else 'auto')]


def h_cursor(n, toks, ws, s, ctx, issues):
    return [(n, s.split(',')[-1].strip())]


def h_logical(n, toks, ws, s, ctx, issues):
    """margin-inline, padding-block, inset-inline-start, ... (left-to-right)"""
    m = re.match(r'^(margin|padding|inset|border)-(inline|block)(?:-(start|end))?(-width|-color)?$', n)
    if not m:
        issues.append(Issue(n, 'write the physical property'))
        return []
    base, axis, edge, suf = m.group(1), m.group(2), m.group(3), m.group(4) or ''
    sides = ('left', 'right') if axis == 'inline' else ('top', 'bottom')
    vals = [V.ser(w) if w[0][0] != 'num' else len_str(w[0]) for w in ws]
    if edge:
        side = sides[0] if edge == 'start' else sides[1]
        return [((side if base == 'inset' else f'{base}-{side}') + suf, ' '.join(vals))]
    a, b = (vals + vals)[:2] if len(vals) == 1 else vals[:2]
    return [((sides[0] if base == 'inset' else f'{base}-{sides[0]}') + suf, a),
            ((sides[1] if base == 'inset' else f'{base}-{sides[1]}') + suf, b)]


def h_direction(n, toks, ws, s, ctx, issues):
    return [('-rmlui-direction', s if s in ('ltr', 'rtl') else 'auto')]


def h_gap(n, toks, ws, s, ctx, issues):
    vals = []
    for w in ws:
        if V.ser(w) == 'normal':
            vals.append('0')
        else:
            vals.append(len_str(w[0]) if w[0][0] == 'num' else V.ser(w))
    return [('gap' if n == 'grid-gap' else n, ' '.join(vals))]


def h_flex(n, toks, ws, s, ctx, issues):
    if s == 'auto':
        return [('flex', '1 1 auto')]
    return [(n, s)]


def h_vertical_align(n, toks, ws, s, ctx, issues):
    return check_keywords(n, s, ws, issues)


HANDLERS = {
    'display': h_display, 'position': h_position, 'overflow': h_overflow, 'overflow-x': h_overflow,
    'overflow-y': h_overflow, 'visibility': h_visibility, 'opacity': h_opacity,
    'width': h_size, 'height': h_size, 'min-width': h_size, 'min-height': h_size, 'max-width': h_size,
    'max-height': h_size, 'flex-basis': h_size,
    'align-items': h_align, 'align-self': h_align, 'align-content': h_align, 'justify-content': h_align,
    'text-align': h_text_align, 'white-space': h_white_space, 'overflow-wrap': h_overflow_wrap,
    'word-wrap': h_overflow_wrap, 'word-break': h_word_break,
    'font-family': h_font_family, 'font-weight': h_font_weight, 'font-size': h_font_size, 'font': h_font,
    'line-height': h_line_height,
    'border': h_border, 'border-top': h_border, 'border-right': h_border, 'border-bottom': h_border,
    'border-left': h_border, 'border-style': h_border_style, 'border-top-style': h_border_style,
    'border-right-style': h_border_style, 'border-bottom-style': h_border_style, 'border-left-style': h_border_style,
    'border-width': h_border_width, 'border-top-width': h_border_width, 'border-right-width': h_border_width,
    'border-bottom-width': h_border_width, 'border-left-width': h_border_width,
    'border-radius': h_radius, 'border-top-left-radius': h_radius, 'border-top-right-radius': h_radius,
    'border-bottom-left-radius': h_radius, 'border-bottom-right-radius': h_radius,
    'outline': h_outline, 'outline-width': h_outline, 'outline-color': h_outline, 'outline-style': h_outline,
    'outline-offset': h_outline,
    'text-decoration': h_text_decoration, 'text-decoration-line': h_text_decoration,
    'text-shadow': h_text_shadow, 'box-shadow': h_box_shadow, 'filter': h_filter, 'backdrop-filter': h_filter,
    'transition': h_transition, 'animation': h_animation, 'transform': h_transform,
    'pointer-events': h_pointer_events, 'cursor': h_cursor, 'direction': h_direction,
    'gap': h_gap, 'row-gap': h_gap, 'column-gap': h_gap, 'grid-gap': h_gap, 'flex': h_flex,
    'vertical-align': h_vertical_align,
}
for _n in ('margin-inline', 'margin-block', 'padding-inline', 'padding-block', 'inset-inline', 'inset-block',
           'margin-inline-start', 'margin-inline-end', 'margin-block-start', 'margin-block-end',
           'padding-inline-start', 'padding-inline-end', 'padding-block-start', 'padding-block-end',
           'inset-inline-start', 'inset-inline-end', 'inset-block-start', 'inset-block-end'):
    HANDLERS[_n] = h_logical

LAYER_PROPS = {'background', 'background-color', 'background-image', 'background-size', 'background-position',
               'background-repeat', 'background-attachment', 'background-origin', 'background-clip',
               'background-position-x', 'background-position-y'}
MASK_PROPS = {'mask', 'mask-image', 'mask-size', 'mask-position', 'mask-repeat', 'mask-mode', 'mask-origin',
              'mask-clip', 'mask-composite', 'mask-type'}
MASK_PROPS |= {'-webkit-' + p for p in MASK_PROPS}
