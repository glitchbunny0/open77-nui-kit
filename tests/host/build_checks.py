#!/usr/bin/env python3
"""scripts/build.py checks, run against a tiny fake RmlUi (one core file, tag 6.3, cloned over file://) so they take
seconds and never touch the real cache. Usage: build_checks.py BUILD_PY WORKDIR [CHECK-PREFIX]
Prints "ok <check>" or "FAIL <check>: why" per check; exits 1 when any failed. Runs on Linux, macOS and Windows: the
cache lock is held from here the way build.py takes it, and the fake git is a script on PATH (git.cmd on Windows).
"""
import os, pathlib, subprocess, sys, time

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


def env(d, path=None):
    e = dict(os.environ, NUIKIT_RMLUI_URL=pathlib.Path(REPO).as_uri(), NUIKIT_RMLUI_TAG='6.3', NUIKIT_RMLUI_DIR=d)
    if path:
        e['PATH'] = path
    return e


def run(d, *args, path=None):
    return subprocess.run([sys.executable, BUILD, *args], env=env(d, path), capture_output=True)


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

sys.exit(1 if failed else 0)
