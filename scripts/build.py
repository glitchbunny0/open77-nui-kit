#!/usr/bin/env python3
"""Build the kit's RmlUi host (host/rmlhost.cpp) against a pinned RmlUi release, on Linux, macOS and Windows. Needs
git and a C++17 compiler; no CMake, no FreeType: the host brings its own null renderer and font engines.
  scripts/build.py [--host DIR] [--out FILE]          (scripts/build.sh runs this)
The compiler: $CXX when set (g++, clang++, cl or clang-cl, by name or path), else the first of g++, clang++, c++ on
PATH. On Windows: cl when it is on PATH (a developer prompt), else g++ or clang++ (MinGW-w64), else the newest Visual
Studio or Build Tools with the C++ workload, found by vswhere, whose environment is loaded here (no developer prompt
needed; CXX=cl without a cl on PATH loads it too).
The RmlUi checkout and its objects live in a cache dir, never in the repo:
  NUIKIT_RMLUI_DIR   default <cache>/open77-nui-kit/rmlui-<tag>; <cache> is $XDG_CACHE_HOME when set, else
                     %LOCALAPPDATA% on Windows and ~/.cache elsewhere
  NUIKIT_RMLUI_TAG   default 6.3; a git checkout in NUIKIT_RMLUI_DIR at another tag is an error, never used silently
  NUIKIT_RMLUI_URL   where the checkout is cloned from (default: RmlUi on GitHub)
The binary is <dir>/build/rmlhost-<hash> (.exe on Windows), the hash taken over the host sources, the tag, the
compiler and its flags: kit checkouts sharing one cache dir never run each other's host, and a changed host/ or
another compiler always gets its own build. RmlUi's own objects are built once per compiler, in <dir>/build/obj-<hash>.
--host builds another host source dir (the suite's mutants); --out writes the binary to FILE instead of the cache
(FILE.exe on Windows when FILE does not end in .exe).
The clone and the core build hold a lock on <dir>.lock, so builds started together wait for each other. A clone goes
to <dir>.tmp.<pid> and is renamed once complete, so a killed clone never leaves a half checkout in <dir>.
Prints the path of the built binary on its last line; everything else goes to stderr. Exit status: 0 built (or
already there), 1 a compile or clone failed, 2 a usage, compiler or cache dir problem.
"""
import argparse, glob, hashlib, os, platform, shlex, shutil, stat, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

WINDOWS = os.name == 'nt'
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = os.environ.get('NUIKIT_RMLUI_TAG') or '6.3'     # Open77's NativeUI is RmlUi 6.3; move this pin when Open77 moves
URL = os.environ.get('NUIKIT_RMLUI_URL') or 'https://github.com/mikke89/RmlUi.git'
GNU_FLAGS = ['-std=c++17', '-O1', '-w', '-DRMLUI_STATIC_LIB']
MSVC_FLAGS = ['/nologo', '/std:c++17', '/O1', '/w', '/EHsc', '/utf-8', '/DRMLUI_STATIC_LIB']


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def die(msg, code=2):
    log('build.py: ' + msg)
    sys.exit(code)


def output(r):
    """what a finished process printed, as text"""
    return (r.stdout or b'').decode('utf-8', 'replace') + (r.stderr or b'').decode('utf-8', 'replace')


# ---- the compiler

class Compiler:
    """kind 'gnu' (g++ / clang++ flags) or 'msvc' (cl / clang-cl flags); cmd: the command, wrappers and all; env: the
    environment it runs in (Visual Studio's when vswhere found it)"""

    def __init__(self, cmd, env=None):
        self.cmd, self.env = cmd, env
        names = [os.path.splitext(os.path.basename(c))[0].lower() for c in cmd]
        self.kind = 'msvc' if any(n in ('cl', 'clang-cl') for n in names) else 'gnu'
        if self.kind == 'msvc':
            self.flags, self.obj, self.target = MSVC_FLAGS, '.obj', ''
            r = self.run(['--version'] if 'clang-cl' in names else [])
            self.ident = next((l.strip() for l in output(r).splitlines() if 'version' in l.lower()), '')
            self.libs = ['shell32.lib', 'user32.lib']   # CommandLineToArgvW; RmlUi's LogDefault calls MessageBox
        else:
            self.flags, self.obj = GNU_FLAGS, '.o'
            self.ident = (output(self.run(['--version'])).splitlines() or [''])[0].strip()
            self.target = output(self.run(['-dumpmachine'])).strip()
            mingw = 'mingw' in self.target or 'windows-gnu' in self.target
            # MinGW: a standalone exe (no libstdc++ DLL to find at run time); shell32 holds CommandLineToArgvW, user32
            # the MessageBox RmlUi's LogDefault calls
            self.libs = (['-static'] if mingw else []) + (['-lshell32', '-luser32'] if WINDOWS else [])
        if not self.ident:
            die(f'{" ".join(cmd)} does not run as a C++ compiler (set CXX to g++, clang++ or cl)')
        self.key = hashlib.sha256('\n'.join([self.kind, self.ident, self.target] + self.flags).encode()).hexdigest()[:12]

    def run(self, args, **kw):
        try:
            return subprocess.run(self.cmd + args, env=self.env, capture_output=True, **kw)
        except OSError as e:
            die(f'cannot run {self.cmd[0]}: {e.strerror or e}')

    def compile_core(self, src, obj):
        if self.kind == 'msvc':
            return self.cmd + self.flags + ['/IInclude', '/c', src, '/Fo' + obj]
        return self.cmd + self.flags + ['-IInclude', '-c', src, '-o', obj]

    def link_host(self, src, include, objs, out, scratch):
        if self.kind == 'msvc':
            return self.cmd + self.flags + ['/I' + include, src, '/Fo' + scratch + os.sep, '/Fe' + out] + objs + self.libs
        return self.cmd + self.flags + ['-I' + include, src] + objs + ['-o', out] + self.libs


def msvc_env():
    """the environment of the newest Visual Studio / Build Tools with the C++ tools (vcvarsall for this machine), or
    None; read with `cmd /u` so that every value arrives as UTF-16, whatever the code page"""
    pf = os.environ.get('ProgramFiles(x86)') or os.environ.get('ProgramFiles') or r'C:\Program Files (x86)'
    vswhere = os.path.join(pf, 'Microsoft Visual Studio', 'Installer', 'vswhere.exe')
    if not os.path.isfile(vswhere):
        return None
    arm = platform.machine().upper() in ('ARM64', 'AARCH64')
    component = 'Microsoft.VisualStudio.Component.VC.Tools.' + ('ARM64' if arm else 'x86.x64')
    r = subprocess.run([vswhere, '-latest', '-products', '*', '-requires', component, '-property', 'installationPath',
                        '-utf8'], capture_output=True)
    paths = r.stdout.decode('utf-8', 'replace').strip().splitlines()
    vcvars = os.path.join(paths[0].strip(), 'VC', 'Auxiliary', 'Build', 'vcvarsall.bat') if paths else ''
    if not os.path.isfile(vcvars):
        return None
    # /s: strip the outer quotes only (the path may hold parentheses); /d: no AutoRun commands
    r = subprocess.run(f'cmd /d /s /u /c ""{vcvars}" {"arm64" if arm else "x64"} >nul && set"', capture_output=True)
    env = {}
    for line in r.stdout.decode('utf-16-le', 'replace').splitlines():
        k, eq, v = line.partition('=')
        if eq and k:
            env[k] = v
    return env if r.returncode == 0 and 'INCLUDE' in {k.upper() for k in env} else None


def find_compiler():
    cxx = os.environ.get('CXX', '').strip()
    if cxx:
        cmd = [cxx] if os.path.isfile(cxx) else [c.strip('"') for c in shlex.split(cxx, posix=not WINDOWS)]
        exe = shutil.which(cmd[0])
        if exe:
            return Compiler([exe] + cmd[1:])
        if WINDOWS and os.path.splitext(os.path.basename(cmd[0]))[0].lower() == 'cl':
            env = msvc_env()
            exe = env and shutil.which('cl', path=next((v for k, v in env.items() if k.upper() == 'PATH'), ''))
            if exe:
                return Compiler([exe] + cmd[1:], env)
            die('CXX is cl, but neither is cl on PATH nor did vswhere find Visual Studio with the C++ tools')
        die(f'CXX is {cxx!r}, which is not on PATH')
    for name in (('cl', 'g++', 'clang++') if WINDOWS else ('g++', 'clang++', 'c++')):
        exe = shutil.which(name)
        if exe:
            return Compiler([exe])
    env = msvc_env() if WINDOWS else None
    exe = env and shutil.which('cl', path=next((v for k, v in env.items() if k.upper() == 'PATH'), ''))
    if exe:
        return Compiler([exe], env)
    die('no C++17 compiler found: install g++ or clang++ (macOS: xcode-select --install; Windows: Visual Studio or '
        'its Build Tools with the C++ workload, or MinGW-w64), or set CXX')


# ---- the cache dir

class Lock:
    """an exclusive lock on a file, held until exit; another process asking for it waits (flock on POSIX, a locked
    byte on Windows)"""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.fh = open(self.path, 'a+b')
        if WINDOWS:
            import msvcrt
            while True:
                try:
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)   # gives up after 10 s: wait on
                    return self
                except OSError:
                    time.sleep(0.2)
        import fcntl
        fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if WINDOWS:
            import msvcrt
            self.fh.seek(0)
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        self.fh.close()


def rmtree(path):
    """remove a tree, git's read-only object files included (Windows refuses to delete those)"""
    def again(func, p, _):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=again)
    else:
        shutil.rmtree(path, onerror=again)


def rename(a, b):
    """os.rename, retried for a while on Windows, where a virus scanner or the indexer may hold a fresh file open"""
    for i in range(50):
        try:
            return os.rename(a, b)
        except PermissionError:
            if not WINDOWS or i == 49:
                raise
            time.sleep(0.1)


def git():
    g = shutil.which('git')
    if not g:
        die('git not found on PATH (it fetches RmlUi)')
    return g


def checkout(d):
    """make sure d holds RmlUi at TAG, cloning it when d does not exist"""
    if not os.path.isdir(os.path.join(d, 'Source', 'Core')):
        if os.path.lexists(d):
            die(f'{d} exists but holds no RmlUi checkout (no Source/Core): remove it or set NUIKIT_RMLUI_DIR')
        for old in glob.glob(glob.escape(d) + '.tmp.*'):   # left by a killed clone (we hold the lock)
            rmtree(old)
        tmp = f'{d}.tmp.{os.getpid()}'
        r = subprocess.run([git(), '-c', 'advice.detachedHead=false', '-c', 'core.autocrlf=false', 'clone', '-q',
                            '--depth', '1', '--branch', TAG, URL, tmp], stdout=sys.stderr)
        if r.returncode:
            die(f'git clone of RmlUi {TAG} from {URL} failed', 1)
        rename(tmp, d)
    if os.path.exists(os.path.join(d, '.git')):
        r = subprocess.run([git(), '-C', d, 'describe', '--tags', '--exact-match'], capture_output=True)
        have = r.stdout.decode('utf-8', 'replace').strip() if r.returncode == 0 else 'no tag'
        if have != TAG:
            die(f"{d} is RmlUi at '{have}', not {TAG} (NUIKIT_RMLUI_TAG): set NUIKIT_RMLUI_DIR to another dir")


def build_core(cc, d, objdir):
    """RmlUi's core (no FontEngineDefault: it needs FreeType), once per compiler"""
    done = os.path.join(objdir, '.core-built')
    if os.path.exists(done):
        return
    log(f'building RmlUi {TAG} core with {cc.ident} (once, about a minute)')
    os.makedirs(objdir, exist_ok=True)
    rel = os.path.relpath(objdir, d)
    srcs = sorted(os.path.relpath(p, d).replace(os.sep, '/')
                  for p in glob.glob(os.path.join(d, 'Source', 'Core', '**', '*.cpp'), recursive=True))
    srcs = [s for s in srcs if 'FontEngineDefault' not in s]

    def one(src):   # relative paths only: a cache under a non-ASCII home never reaches the compiler's command line
        return src, subprocess.run(cc.compile_core(src, os.path.join(rel, src.replace('/', '_') + cc.obj)),
                                   cwd=d, env=cc.env, capture_output=True)
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        bad = [(s, r) for s, r in pool.map(one, srcs) if r.returncode]
    for s, r in bad[:3]:
        log(f'== {s}\n{output(r).strip()[-3000:]}')
    if bad or not srcs:
        die(f'{len(bad)} of {len(srcs)} RmlUi {TAG} core files did not compile with {cc.ident}', 1)
    open(done, 'w').close()


def host_hash(cc, src):
    h = hashlib.sha256('\n'.join([TAG, cc.kind, cc.ident, cc.target] + cc.flags + cc.libs).encode() + b'\n')
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                h.update(b'== ' + name.encode('utf-8', 'surrogateescape') + b'\n' + f.read())
    return h.hexdigest()[:16]


def main():
    for s in (sys.stdout, sys.stderr):   # UTF-8 and \n on every OS: callers read the path off the last line
        if hasattr(s, 'reconfigure'):
            s.reconfigure(encoding='utf-8', errors='backslashreplace', newline='\n')
    ap = argparse.ArgumentParser(prog='scripts/build.py', description='Build the kit\'s RmlUi host (see the top of '
                                 'scripts/build.py for the settings).')
    ap.add_argument('--host', help='the host source dir to build (default: the kit\'s host/)')
    ap.add_argument('--out', help='write the binary here instead of the cache dir')
    a = ap.parse_args()
    src = os.path.abspath(a.host or os.path.join(KIT, 'host'))
    if not os.path.isfile(os.path.join(src, 'rmlhost.cpp')):
        die(f'no rmlhost.cpp in {src}')
    d = os.path.abspath(os.path.expanduser(os.environ.get('NUIKIT_RMLUI_DIR') or os.path.join(
        os.environ.get('XDG_CACHE_HOME') or (WINDOWS and os.environ.get('LOCALAPPDATA')) or os.path.expanduser(
            os.path.join('~', '.cache')), 'open77-nui-kit', 'rmlui-' + TAG)))
    cc = find_compiler()
    os.makedirs(os.path.dirname(d), exist_ok=True)
    objdir = os.path.join(d, 'build', 'obj-' + cc.key)
    with Lock(d + '.lock'):
        checkout(d)
        build_core(cc, d, objdir)
    # the host needs no lock: it is linked to a private name, then renamed into place
    exe = '.exe' if WINDOWS else ''
    if a.out:
        out = os.path.abspath(a.out)
        out += exe if not out.lower().endswith(exe) else ''
    else:
        out = os.path.join(d, 'build', f'rmlhost-{host_hash(cc, src)}{exe}')
    if a.out or not os.path.isfile(out):
        log('building rmlhost')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = f'{out[:len(out) - len(exe)]}.new.{os.getpid()}{exe}'
        scratch = f'{tmp}.obj'
        os.makedirs(scratch, exist_ok=True)
        objs = sorted(f for f in os.listdir(objdir) if f.endswith(cc.obj))
        try:
            r = subprocess.run(cc.link_host(os.path.join(src, 'rmlhost.cpp'), os.path.join(d, 'Include'), objs, tmp,
                                            scratch), cwd=objdir, env=cc.env, capture_output=True)
        finally:
            rmtree(scratch)
        if r.returncode or not os.path.isfile(tmp):
            log(output(r).strip()[-4000:])
            if os.path.exists(tmp):
                os.remove(tmp)
            die('rmlhost did not build', 1)
        try:
            os.replace(tmp, out)
        except PermissionError:   # Windows: another build of the same sources is running it
            if a.out or not os.path.isfile(out):
                raise
            os.remove(tmp)
    print(out)


if __name__ == '__main__':
    main()
