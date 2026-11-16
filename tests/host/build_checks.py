#!/usr/bin/env python3
"""scripts/build.py checks, run against a tiny fake RmlUi (one core file, tag 6.3, cloned over file://) so they take
seconds and never touch the real cache. Usage: build_checks.py BUILD_PY WORKDIR [CHECK-PREFIX]
Prints "ok <check>" or "FAIL <check>: why" per check; exits 1 when any failed. Runs on Linux, macOS and Windows: the
cache lock is held from here the way build.py takes it, and the fake git is a script on PATH (git.cmd on Windows).
"""
import hashlib, importlib.util, json, os, pathlib, subprocess, sys, time, zipfile

WINDOWS = os.name == 'nt'
BUILD, W = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
ONLY = sys.argv[3] if len(sys.argv) > 3 else ''
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding='utf-8', errors='backslashreplace', newline='\n')
os.makedirs(W, exist_ok=True)
failed = []


def ok(c):
    print('ok ' + c)


def bad(c, why):
    print(f'FAIL {c}: {why}')
    failed.append(c)


def want(c):
    return not ONLY or c.startswith(ONLY)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


REPO = os.path.join(W, 'fake-rmlui')
if not os.path.isdir(os.path.join(REPO, '.git')):
    write(os.path.join(REPO, 'Source', 'Core', 'Core.cpp'), 'int fake_core() { return 7; }\n')
    for args in (['init', '-q'], ['add', '-A'],
                 ['-c', 'user.name=kit', '-c', 'user.email=kit@example.invalid', 'commit', '-q', '-m', 'fake'],
                 ['tag', '6.3']):
        subprocess.run(['git'] + args, cwd=REPO, check=True, capture_output=True)


def mkhost(d, word):   # a host source dir whose binary prints WORD
    write(os.path.join(d, 'rmlhost.cpp'),
          '#include <cstdio>\nint fake_core();\nint main() { std::puts("%s"); return fake_core() == 7 ? 0 : 1; }\n' % word)
    return d


HOST_A, HOST_B = mkhost(os.path.join(W, 'hostA'), 'A'), mkhost(os.path.join(W, 'hostB'), 'B')


def env(d, path=None, **extra):
    # no prebuilt host unless a check asks for one: these checks are about building, and must never fetch
    e = dict(os.environ, NUIKIT_RMLUI_URL=pathlib.Path(REPO).as_uri(), NUIKIT_RMLUI_TAG='6.3', NUIKIT_RMLUI_DIR=d,
             NUIKIT_PREBUILT='0')
    if path:
        e['PATH'] = path
    e.update(extra)
    return e


def run(d, *args, path=None, **extra):
    return subprocess.run([sys.executable, BUILD, *args], env=env(d, path, **extra), capture_output=True)


def last(r):
    lines = r.stdout.decode('utf-8', 'replace').strip().splitlines()
    return lines[-1] if r.returncode == 0 and lines else ''


def says(binary):
    """what a built fake host prints, or None when there is none"""
    if not binary or not os.path.isfile(binary):
        return None
    return subprocess.run([binary], capture_output=True).stdout.decode('utf-8', 'replace').strip()


class Held:
    """the cache lock, held by this process the way build.py takes it (flock; one locked byte on Windows)"""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.fh = open(self.path, 'a+b')
        if WINDOWS:
            import msvcrt
            self.fh.seek(0)
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def __exit__(self, *exc):
        if WINDOWS:
            import msvcrt
            self.fh.seek(0)
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        self.fh.close()


c = 'build: two host sources sharing one cache dir get their own binaries'
if want(c):
    d = os.path.join(W, 'c1', 'rmlui')
    a, b, a2 = (last(run(d, '--host', h)) for h in (HOST_A, HOST_B, HOST_A))
    if not a or a == b or a != a2:
        bad(c, f'paths A={a} B={b} A again={a2}')
    elif says(a) != 'A' or says(b) != 'B':
        bad(c, f"A runs {says(a)!r}, B runs {says(b)!r}")
    else:
        ok(c)

c = 'build: a build waits while another holds the cache lock'
if want(c):
    d = os.path.join(W, 'c2', 'rmlui')
    run(d, '--host', HOST_A)   # clone + core first, so the timed builds only have the lock to wait for
    t = time.time()
    run(d, '--host', HOST_B, '--out', os.path.join(W, 'c2', 'free'))
    hold = 2 * (time.time() - t) + 1   # twice what a whole build takes here: a build that did not wait is done by then
    with Held(d + '.lock'):
        p = subprocess.Popen([sys.executable, BUILD, '--host', HOST_B, '--out', os.path.join(W, 'c2', 'held')],
                             env=env(d), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(hold)
        early = p.poll()
    out, _ = p.communicate(timeout=hold + 300)
    binary = (out.decode('utf-8', 'replace').strip().splitlines() or [''])[-1]
    if early is not None:
        bad(c, f'finished (rc {early}) while the lock was held')
    elif says(binary) != 'B':
        bad(c, 'no build after the lock was released')
    else:
        ok(c)

c = 'build: a checkout at another tag is refused'
if want(c):
    d = os.path.join(W, 'c3', 'rmlui')
    run(d, '--host', HOST_A)
    subprocess.run(['git', '-C', d, 'tag', '5.1'], capture_output=True)
    subprocess.run(['git', '-C', d, 'tag', '-d', '6.3'], capture_output=True)
    r = run(d, '--host', HOST_A)
    msg = (r.stdout + r.stderr).decode('utf-8', 'replace')
    if r.returncode == 0:
        bad(c, 'a 5.1 checkout was used for tag 6.3')
    elif 'not 6.3' not in msg:
        bad(c, f'no message naming the tag: {msg.strip()}')
    else:
        ok(c)

c = 'build: a killed clone leaves no half checkout behind'
if want(c):
    d = os.path.join(W, 'c4', 'rmlui')
    fake = os.path.join(W, 'fakegit')
    # a git that dies after creating the destination's .git, as a clone killed half way does
    if WINDOWS:
        write(os.path.join(fake, 'git.cmd'), '@echo off\r\nfor %%a in (%*) do set "dest=%%~a"\r\n'
                                             'mkdir "%dest%\\.git"\r\nexit /b 137\r\n')
    else:
        write(os.path.join(fake, 'git'), '#!/bin/sh\nfor a; do dest="$a"; done\nmkdir -p "$dest/.git"\nexit 137\n')
        os.chmod(os.path.join(fake, 'git'), 0o755)
    r1 = run(d, '--host', HOST_A, path=fake + os.pathsep + os.environ['PATH'])
    p = last(run(d, '--host', HOST_A))
    if r1.returncode == 0:
        bad(c, 'the killed clone counted as a build')
    elif says(p) != 'A':
        bad(c, f'the next build failed: {p or "no binary"}')
    else:
        ok(c)

c = 'build: the compiler found is remembered, and probed again when it changed'
if want(c):
    d = os.path.join(W, 'c5', 'rmlui')
    memo = os.path.join(W, 'c5', 'compilers.json')
    a = last(run(d, '--host', HOST_A))

    def edit_memo(change):
        with open(memo, encoding='utf-8') as f:
            known = json.load(f)
        for e in known.values():
            change(e)
        with open(memo, 'w', encoding='utf-8') as f:
            json.dump(known, f)
    if not os.path.isfile(memo) or says(a) != 'A':
        bad(c, f'no compilers.json next to the cache dir after a build ({a or "no binary"})')
    else:
        edit_memo(lambda e: e.update(ident=e['ident'] + ' (remembered)'))   # the remembered ident names the binary
        b = last(run(d, '--host', HOST_A))
        edit_memo(lambda e: e.update(stamp=[0, 0]))   # as if the compiler had changed since
        again = last(run(d, '--host', HOST_A))
        if not b or b == a or says(b) != 'A':
            bad(c, f'the remembered compiler was not used: {a} then {b}')
        elif again != a:
            bad(c, f'a changed compiler was not probed again: {again}, want {a}')
        else:
            ok(c)

# ---- prebuilt: a fake release (a file:// folder) holding the binary built for HOST_A's sources
spec = importlib.util.spec_from_file_location('build_under_test', BUILD)
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)   # its source_hash and platform_tag name the release asset, as the build under test does
PLAT = B.platform_tag()


def fake_release(where, binary, digest=None, extra=()):
    """a release folder for HOST_A: v<VERSION>/<asset>.zip and SHA256SUMS (digest: what SHA256SUMS claims). binary: a
    file, or bytes to ship as the host; extra: more zip members, as (name, text)"""
    name = B.asset_name(HOST_A, PLAT)
    folder = os.path.join(where, 'v' + B.kit_version())
    os.makedirs(folder, exist_ok=True)
    z = os.path.join(folder, name + '.zip')
    with zipfile.ZipFile(z, 'w') as zf:
        if isinstance(binary, bytes):
            zf.writestr(f'{name}/rmlhost{B.EXE}', binary)
        else:
            zf.write(binary, f'{name}/rmlhost{B.EXE}')
        zf.writestr(f'{name}/LICENSE', 'MIT')
        for member, text in extra:
            zf.writestr(member, text)
    with open(z, 'rb') as f:
        real = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(folder, 'SHA256SUMS'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{digest or real}  {name}.zip\n')
    return pathlib.Path(where).as_uri()


PRE = dict(NUIKIT_PREBUILT='')   # the prebuilt path on, as for a user
if not PLAT or not B.kit_version():
    print('skip build: the prebuilt checks (no release binary for this platform, or no VERSION file)')
else:
    built_a = last(run(os.path.join(W, 'c6', 'src', 'rmlui'), '--host', HOST_A))   # the binary a release would ship

    c = 'prebuilt: the release binary for these host sources is fetched, checked and used, then kept'
    if want(c):
        d = os.path.join(W, 'c6', 'rmlui')
        url = fake_release(os.path.join(W, 'c6', 'rel'), built_a)
        nocc = os.path.join(W, 'no-such-compiler')   # a source build cannot happen: the release must serve
        first = last(run(d, '--host', HOST_A, CXX=nocc, NUIKIT_PREBUILT_URL=url, **PRE))
        again = last(run(d, '--host', HOST_A, CXX=nocc, NUIKIT_PREBUILT_URL=pathlib.Path(W, 'gone').as_uri(), **PRE))
        inside = os.path.join(W, 'c6', 'prebuilt')
        if not first or not first.startswith(inside) or says(first) != 'A':
            bad(c, f'the release binary was not used: {first or "no binary"}')
        elif again != first:
            bad(c, f'a second run without the release did not use the one fetched: {again or "no binary"}')
        else:
            ok(c)

    c = 'prebuilt: a download whose SHA-256 is not the release\'s is refused, and the host is built from source'
    if want(c):
        d = os.path.join(W, 'c7', 'rmlui')
        url = fake_release(os.path.join(W, 'c7', 'rel'), built_a, digest='0' * 64)
        r = run(d, '--host', HOST_A, NUIKIT_PREBUILT_URL=url, **PRE)
        p = last(r)
        if not p or p.startswith(os.path.join(W, 'c7', 'prebuilt')) or says(p) != 'A':
            bad(c, f'the binary used: {p or "none"}')
        elif b'SHA-256' not in r.stderr:
            bad(c, 'no word of the SHA-256 that did not match')
        else:
            ok(c)

    c = 'prebuilt: NUIKIT_PREBUILT=0 never fetches'
    if want(c):
        d = os.path.join(W, 'c8', 'rmlui')
        url = fake_release(os.path.join(W, 'c8', 'rel'), built_a)
        p = last(run(d, '--host', HOST_A, NUIKIT_PREBUILT_URL=url))   # env() sets NUIKIT_PREBUILT=0
        if not p or p.startswith(os.path.join(W, 'c8', 'prebuilt')):
            bad(c, f'the binary used: {p or "none"}')
        else:
            ok(c)

    def refused(c, n, word, **release):
        """a release for HOST_A made with **release is not used: the host is built from source, stderr says word"""
        url = fake_release(os.path.join(W, n, 'rel'), release.pop('binary', built_a), **release)
        r = run(os.path.join(W, n, 'rmlui'), '--host', HOST_A, NUIKIT_PREBUILT_URL=url, **PRE)
        p = last(r)
        if not p or p.startswith(os.path.join(W, n, 'prebuilt')) or says(p) != 'A':   # never runs a refused one
            bad(c, f'the binary used: {p or "none"}')
        elif word not in r.stderr.decode('utf-8', 'replace'):
            bad(c, f'no {word!r} in: {r.stderr.decode("utf-8", "replace").strip()[-300:]}')
        else:
            ok(c)

    c = 'prebuilt: a zip holding files outside its folder is refused, and the host is built from source'
    if want(c):
        refused(c, 'c9', 'outside', extra=[('elsewhere/x.txt', 'x'), ('../up.txt', 'x')])

    c = 'prebuilt: a binary that does not start here is refused, and the host is built from source'
    if want(c):
        refused(c, 'c10', 'does not run here', binary=b'not a program for this machine\n')

    c = 'prebuilt: with no release binary and no compiler, the error says why for both'
    if want(c):
        r = run(os.path.join(W, 'c11', 'rmlui'), '--host', HOST_A, CXX=os.path.join(W, 'no-such-compiler'),
                NUIKIT_PREBUILT_URL=pathlib.Path(W, 'c11', 'no-release').as_uri(), **PRE)
        err = r.stderr.decode('utf-8', 'replace')
        if r.returncode != 2:
            bad(c, f'exit {r.returncode}, want 2')
        elif not all(w in err for w in ('no prebuilt host', 'no release v', 'none can be built', 'no-such-compiler')):
            bad(c, f'the message: {err.strip()[-300:]}')
        else:
            ok(c)

sys.exit(1 if failed else 0)
