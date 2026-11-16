#!/usr/bin/env python3
"""Build the kit's RmlUi host (host/rmlhost.cpp) against a pinned RmlUi release, on Linux, macOS and Windows. Needs
git and a C++17 compiler; no CMake, no FreeType: the host brings its own null renderer and font engines.
  scripts/build.py [--host DIR] [--out FILE]          (scripts/build.sh runs this)
The compiler: $CXX when set (g++, clang++, cl or clang-cl, by name or path), else the first of g++, clang++, c++ on
PATH. On Windows: cl when it is on PATH (a developer prompt), else g++ or clang++ (MinGW-w64), else the newest Visual
Studio or Build Tools with the C++ workload, found by vswhere, whose environment is loaded here (no developer prompt
needed; CXX=cl without a cl on PATH loads it too).
The compiler found is remembered in <cache>/open77-nui-kit/compilers.json (probing Visual Studio takes seconds) while
CXX, PATH and the compiler's executable stay as they were.
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
Prebuilt: on Linux (x86-64, arm64), macOS and Windows a release of the kit carries the host for its host sources.
When no build of this checkout's host is there yet, the release named in VERSION is asked for the binary built from
exactly these host sources (named after their hash, so another checkout never gets it): it is checked against the
release's SHA256SUMS, run once, and kept in <cache>/open77-nui-kit/prebuilt. Without one (sources changed since the
release, no network) the host is built from source as above. NUIKIT_PREBUILT=0 always builds from source;
NUIKIT_PREBUILT_URL replaces https://github.com/<repo>/releases/download (a mirror, or a file:// folder).
--release DIR builds the binary a release ships for this platform (static: musl on Linux, the C runtime linked in on
Windows; one universal file on macOS) and zips it with the licences into DIR; --license FILE adds one more licence.
Prints the path of the built binary on its last line; everything else goes to stderr. Exit status: 0 built (or
already there), 1 a compile or clone failed, 2 a usage, compiler or cache dir problem.
"""
import argparse, glob, hashlib, io, json, os, platform, shlex, shutil, stat, subprocess, sys, time, zipfile
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

WINDOWS = os.name == 'nt'
EXE = '.exe' if WINDOWS else ''
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = os.environ.get('NUIKIT_RMLUI_TAG') or '6.3'     # Open77's NativeUI is RmlUi 6.3; move this pin when Open77 moves
URL = os.environ.get('NUIKIT_RMLUI_URL') or 'https://github.com/mikke89/RmlUi.git'
GNU_FLAGS = ['-std=c++17', '-O1', '-w', '-DRMLUI_STATIC_LIB']
MSVC_FLAGS = ['/nologo', '/std:c++17', '/O1', '/w', '/EHsc', '/utf-8', '/DRMLUI_STATIC_LIB']
# what a release binary adds per platform, (compile flags, link flags): it must run where nothing is installed
RELEASE_FLAGS = {
    'linux': ([], ['-static', '-s']),                                    # musl, linked whole: any distro; stripped
    'macos': (['-arch', 'arm64', '-arch', 'x86_64', '-mmacosx-version-min=11.0'], []),   # one file for both CPUs
    'windows': (['/MT'], []),                                                     # the C runtime linked in
}
RELEASES = os.environ.get('NUIKIT_PREBUILT_URL') or 'https://github.com/glitchbunny0/open77-nui-kit/releases/download'


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def die(msg, code=2):
    log('build.py: ' + msg)
    sys.exit(code)


def output(r):
    """what a finished process printed, as text"""
    return (r.stdout or b'').decode('utf-8', 'replace') + (r.stderr or b'').decode('utf-8', 'replace')


# ---- the compiler

class NoCompiler(Exception):
    """no C++ compiler to build with (the message says why)"""


NO_COMPILER = ('install g++ or clang++ (macOS: xcode-select --install; Windows: Visual Studio or its Build Tools with '
               'the C++ workload, or MinGW-w64), or set CXX')


class Compiler:
    """kind 'gnu' (g++ / clang++ flags) or 'msvc' (cl / clang-cl flags); cmd: the command, wrappers and all; delta: what
    the environment it runs in adds (Visual Studio's, when vswhere found it); ident and target: what it says it is,
    asked when not given (a remembered compiler)"""

    def __init__(self, cmd, delta=None, ident=None, target=None):
        self.cmd, self.delta = cmd, delta or {}
        self.env = dict(os.environ, **self.delta) if self.delta else None
        names = [os.path.splitext(os.path.basename(c))[0].lower() for c in cmd]
        self.kind = 'msvc' if any(n in ('cl', 'clang-cl') for n in names) else 'gnu'
        if ident is None and self.kind == 'msvc':
            r = self.run(['--version'] if 'clang-cl' in names else [])
            ident, target = next((l.strip() for l in output(r).splitlines() if 'version' in l.lower()), ''), ''
        elif ident is None:
            ident = (output(self.run(['--version'])).splitlines() or [''])[0].strip()
            target = output(self.run(['-dumpmachine'])).strip()
        self.ident, self.target = ident, target
        if self.kind == 'msvc':
            self.flags, self.obj = MSVC_FLAGS, '.obj'
            self.libs = ['shell32.lib', 'user32.lib']   # CommandLineToArgvW; RmlUi's LogDefault calls MessageBox
        else:
            self.flags, self.obj = GNU_FLAGS, '.o'
            mingw = 'mingw' in target or 'windows-gnu' in target
            # MinGW: a standalone exe (no libstdc++ DLL to find at run time); shell32 holds CommandLineToArgvW, user32
            # the MessageBox RmlUi's LogDefault calls
            self.libs = (['-static'] if mingw else []) + (['-lshell32', '-luser32'] if WINDOWS else [])
        if not self.ident:
            raise NoCompiler(f'{" ".join(cmd)} does not run as a C++ compiler (set CXX to g++, clang++ or cl)')
        self.rekey()

    def rekey(self):
        """the name of the folder RmlUi's objects are built into: one per compiler and compile flags"""
        self.key = hashlib.sha256('\n'.join([self.kind, self.ident, self.target] + self.flags).encode()).hexdigest()[:12]

    def run(self, args, **kw):
        try:
            return subprocess.run(self.cmd + args, env=self.env, capture_output=True, **kw)
        except OSError as e:
            raise NoCompiler(f'cannot run {self.cmd[0]}: {e.strerror or e}')

    def compile_core(self, src, obj):
        if self.kind == 'msvc':
            return self.cmd + self.flags + ['/IInclude', '/c', src, '/Fo' + obj]
        return self.cmd + self.flags + ['-IInclude', '-c', src, '-o', obj]

    def link_host(self, src, include, objs, out, scratch):
        if self.kind == 'msvc':
            return self.cmd + self.flags + ['/I' + include, src, '/Fo' + scratch + os.sep, '/Fe' + out] + objs + self.libs
        return self.cmd + self.flags + ['-I' + include, src] + objs + ['-o', out] + self.libs


def msvc_env():
    """what the environment of the newest Visual Studio / Build Tools with the C++ tools adds (vcvarsall for this
    machine; names upper case, as os.environ has them on Windows), or None; read with `cmd /u` so that every value
    arrives as UTF-16, whatever the code page"""
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
            env[k.upper()] = v
    if r.returncode or 'INCLUDE' not in env:
        return None
    return {k: v for k, v in env.items() if os.environ.get(k) != v}


def probe_compiler():
    cxx = os.environ.get('CXX', '').strip()
    if cxx:
        cmd = [cxx] if os.path.isfile(cxx) else [c.strip('"') for c in shlex.split(cxx, posix=not WINDOWS)]
        exe = shutil.which(cmd[0])
        if exe:
            return Compiler([exe] + cmd[1:])
        if WINDOWS and os.path.splitext(os.path.basename(cmd[0]))[0].lower() == 'cl':
            delta = msvc_env()
            exe = delta and shutil.which('cl', path=delta.get('PATH', os.environ.get('PATH', '')))
            if exe:
                return Compiler([exe] + cmd[1:], delta)
            raise NoCompiler('CXX is cl, but neither is cl on PATH nor did vswhere find Visual Studio with the C++ tools')
        raise NoCompiler(f'CXX is {cxx!r}, which is not on PATH')
    for name in (('cl', 'g++', 'clang++') if WINDOWS else ('g++', 'clang++', 'c++')):
        exe = shutil.which(name)
        if exe:
            return Compiler([exe])
    delta = msvc_env() if WINDOWS else None
    exe = delta and shutil.which('cl', path=delta.get('PATH', os.environ.get('PATH', '')))
    if exe:
        return Compiler([exe], delta)
    raise NoCompiler('no C++17 compiler found: ' + NO_COMPILER)


def stamp(path):
    """[size, mtime] of a file: a compiler updated in place is probed again"""
    try:
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return None


def find_compiler(memo, required=True):
    """the compiler, remembered in memo (a JSON file by the cache dir): probing takes seconds with Visual Studio
    (vswhere, then vcvarsall), and every tool run asks. An entry holds while CXX and PATH are what they were and the
    compiler's executable has the size and time it had; else the compiler is probed again. Without one: exit with the
    reason, or (required=False) None, with the reason in find_compiler.why."""
    key = hashlib.sha256(json.dumps([os.environ.get('CXX', ''), os.environ.get('PATH', ''), sys.platform,
                                     platform.machine()]).encode()).hexdigest()[:16]
    try:
        with open(memo, encoding='utf-8') as f:
            known = json.load(f)
    except (OSError, ValueError):
        known = {}
    entry = known.get(key) if isinstance(known, dict) else None
    try:
        if entry and entry['stamp'] and stamp(entry['cmd'][0]) == entry['stamp']:
            return Compiler(entry['cmd'], entry['delta'], entry['ident'], entry['target'])
    except (KeyError, TypeError, IndexError):
        pass   # an entry of another shape: probe
    try:
        cc = probe_compiler()
    except NoCompiler as e:
        if required:
            die(str(e))
        find_compiler.why = str(e)
        return None
    known = {k: v for k, v in (known.items() if isinstance(known, dict) else []) if k != key}
    known = dict(list(known.items())[-31:], **{key: {'cmd': cc.cmd, 'delta': cc.delta, 'ident': cc.ident,
                                                     'target': cc.target, 'stamp': stamp(cc.cmd[0])}})
    tmp = f'{memo}.{os.getpid()}.tmp'
    try:   # written whole, then renamed: a build reading it at the same time never sees half a file
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(known, f, indent=1)
        os.replace(tmp, memo)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
    return cc


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


def hash_sources(h, src):
    """add the files of the host source dir to the hash h, by name and content"""
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                h.update(b'== ' + name.encode('utf-8', 'surrogateescape') + b'\n' + f.read())
    return h.hexdigest()[:16]


def host_hash(cc, src):
    return hash_sources(hashlib.sha256('\n'.join([TAG, cc.kind, cc.ident, cc.target] + cc.flags + cc.libs).encode()
                                      + b'\n'), src)


def host_path(cc, src, d):
    return os.path.join(d, 'build', f'rmlhost-{host_hash(cc, src)}{EXE}')


# ---- release binaries

def platform_tag():
    """the release binary that runs here (Windows on arm64 runs the x86-64 one, emulated), or None"""
    m = platform.machine().lower()
    if sys.platform == 'darwin':
        return 'macos-universal'
    if WINDOWS:
        return 'windows-x86_64' if m in ('amd64', 'x86_64', 'arm64') else None
    if sys.platform.startswith('linux'):
        return {'x86_64': 'linux-x86_64', 'amd64': 'linux-x86_64', 'aarch64': 'linux-aarch64',
                'arm64': 'linux-aarch64'}.get(m)
    return None


def source_hash(src):
    """what a release binary is named after: RmlUi's tag, the flags of every build and of releases, the host sources.
    No compiler: one binary per platform serves every checkout with these sources."""
    return hash_sources(hashlib.sha256(json.dumps([TAG, GNU_FLAGS, MSVC_FLAGS, RELEASE_FLAGS], sort_keys=True).encode()
                                       + b'\n'), src)


def asset_name(src, plat):
    return f'rmlhost-{source_hash(src)}-{plat}'


def kit_version():
    """the release this kit is (VERSION, next to scripts/), or None"""
    try:
        with open(os.path.join(KIT, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip() or None
    except OSError:
        return None


def short(e):
    return (str(getattr(e, 'reason', '') or e) or type(e).__name__)[:160]


def fetch(url):
    """the bytes at url (https or file://). curl when Python's own TLS has no root certificates (a python.org Python
    on macOS until its Install Certificates step)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'open77-nui-kit'}),
                                    timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as e:
        curl = shutil.which('curl')
        if not (curl and url.startswith('https://') and 'CERTIFICATE' in str(e.reason).upper()):
            raise
        r = subprocess.run([curl, '-fsSL', '--max-time', '120', url], capture_output=True)
        if r.returncode:
            raise OSError(f'curl: {r.stderr.decode("utf-8", "replace").strip()[:160]}')
        return r.stdout


def prebuilt_dir(d):
    return os.path.join(os.path.dirname(d), 'prebuilt')


def cached_prebuilt(src, d):
    plat = platform_tag()
    p = plat and os.path.join(prebuilt_dir(d), asset_name(src, plat), 'rmlhost' + EXE)
    return p if p and os.path.isfile(p) else None


def starts(binary):
    """the binary runs here: without arguments the host prints its usage and exits 2; a missing library, the wrong
    CPU or a crash shows as an OSError, a signal or an exit code past 255"""
    try:
        r = subprocess.run([binary], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return 0 <= r.returncode <= 255


def fetch_prebuilt(src, d):
    """(path, None): the release binary for these host sources, downloaded, checked against the release's SHA256SUMS,
    run once and unpacked into the cache. (None, why) when there is none."""
    plat, version = platform_tag(), kit_version()
    if not plat:
        return None, f'no release binary is made for {sys.platform} on {platform.machine()}'
    if not version:
        return None, f'no VERSION file in {KIT}'
    name = asset_name(src, plat)
    base = f'{RELEASES.rstrip("/")}/v{version}'
    try:
        sums = fetch(f'{base}/SHA256SUMS').decode('utf-8', 'replace')
    except Exception as e:   # noqa: BLE001 - offline, no such release yet: build instead
        return None, f'no release v{version} to fetch from ({short(e)})'
    want = next((parts[0].lower() for parts in (l.split() for l in sums.splitlines())
                 if len(parts) == 2 and parts[1].lstrip('*') == name + '.zip'), None)
    if not want:
        return None, f'release v{version} has no {name}.zip (the host sources changed since that release)'
    log(f'fetching the prebuilt host {name} from release v{version}')
    try:
        data = fetch(f'{base}/{name}.zip')
    except Exception as e:   # noqa: BLE001
        return None, f'{name}.zip did not download ({short(e)})'
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        return None, f'{name}.zip has SHA-256 {got}, the release lists {want}: not used'
    root = prebuilt_dir(d)
    os.makedirs(root, exist_ok=True)
    tmp, final = os.path.join(root, f'{name}.tmp.{os.getpid()}'), os.path.join(root, name)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if not all(m.startswith(name + '/') and '..' not in m.split('/') for m in z.namelist()):
                return None, f'{name}.zip holds files outside its {name}/ folder: not used'
            z.extractall(tmp)
        binary = os.path.join(tmp, name, 'rmlhost' + EXE)
        if not os.path.isfile(binary):
            return None, f'{name}.zip has no rmlhost{EXE}'
        if not WINDOWS:
            os.chmod(binary, 0o755)
        if not starts(binary):
            return None, f'{name} does not run here'
        try:
            rename(os.path.join(tmp, name), final)
        except OSError:
            if not os.path.isfile(os.path.join(final, 'rmlhost' + EXE)):   # else another build unpacked it first
                raise
    finally:
        if os.path.lexists(tmp):
            rmtree(tmp)
    return os.path.join(final, 'rmlhost' + EXE), None


# ---- the build

def link(cc, src, d, objdir, out, replace=False):
    """link the host (src/rmlhost.cpp and RmlUi's objects) to out, through a private name"""
    log('building rmlhost')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = f'{out[:len(out) - len(EXE)]}.new.{os.getpid()}{EXE}'
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
        if replace or not os.path.isfile(out):
            raise
        os.remove(tmp)


def release(a, src, d, memo):
    """--release DIR: the binary a release ships for this platform, zipped with the licences; prints the zip"""
    plat = platform_tag()
    kind = (plat or '').split('-')[0]
    if kind not in RELEASE_FLAGS:
        die(f'no release binary is made for {sys.platform} on {platform.machine()}')
    cc = find_compiler(memo)
    if kind == 'linux' and 'musl' not in cc.target:
        die(f'a Linux release binary is built with musl (Alpine), so that it runs on any distro; this is {cc.target}')
    if kind == 'windows' and cc.kind != 'msvc':
        die('a Windows release binary is built with MSVC (CXX=cl)')
    extra, libs = RELEASE_FLAGS[kind]
    cc.flags, cc.libs = cc.flags + extra, cc.libs + libs
    cc.rekey()
    objdir = os.path.join(d, 'build', 'obj-' + cc.key)
    with Lock(d + '.lock'):
        checkout(d)
        build_core(cc, d, objdir)
    name = asset_name(src, plat)
    folder = os.path.join(os.path.abspath(a.release), name)
    if os.path.lexists(folder):
        rmtree(folder)
    link(cc, src, d, objdir, os.path.join(folder, 'rmlhost' + EXE), replace=True)
    files = [(os.path.join(KIT, 'LICENSE'), 'LICENSE'), (os.path.join(KIT, 'NOTICE'), 'NOTICE'),
             (os.path.join(d, 'LICENSE.txt'), 'LICENSE.RmlUi.txt')]
    files += [(f, 'LICENSE.' + os.path.basename(f)) for f in a.license]
    for f, as_name in files:
        if not os.path.isfile(f):
            die(f'no such licence file: {f}')
        shutil.copyfile(f, os.path.join(folder, as_name))
    commit = os.environ.get('GITHUB_SHA') or subprocess.run([git(), '-C', KIT, 'rev-parse', 'HEAD'],
                                                            capture_output=True).stdout.decode().strip()
    with open(os.path.join(folder, 'BUILD.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'open77-nui-kit {kit_version()} ({commit or "no commit"})\nhost sources {source_hash(src)}\n'
                f'RmlUi {TAG}\ncompiler {cc.ident} ({cc.target or cc.kind})\nflags {" ".join(cc.flags + cc.libs)}\n')
    out = folder + '.zip'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(folder)):
            info = zipfile.ZipInfo(f'{name}/{fn}', date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = (0o755 if fn.startswith('rmlhost') else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(os.path.join(folder, fn), 'rb') as fh:
                z.writestr(info, fh.read())
    print(out)


def main():
    for s in (sys.stdout, sys.stderr):   # UTF-8 and \n on every OS: callers read the path off the last line
        if hasattr(s, 'reconfigure'):
            s.reconfigure(encoding='utf-8', errors='backslashreplace', newline='\n')
    ap = argparse.ArgumentParser(prog='scripts/build.py', description='Build the kit\'s RmlUi host (see the top of '
                                 'scripts/build.py for the settings).')
    ap.add_argument('--host', help='the host source dir to build (default: the kit\'s host/)')
    ap.add_argument('--out', help='write the binary here instead of the cache dir')
    ap.add_argument('--release', metavar='DIR', help='build the binary a release ships for this platform, zipped')
    ap.add_argument('--license', action='append', default=[], help='one more licence file for --release')
    a = ap.parse_args()
    src = os.path.abspath(a.host or os.path.join(KIT, 'host'))
    if not os.path.isfile(os.path.join(src, 'rmlhost.cpp')):
        die(f'no rmlhost.cpp in {src}')
    d = os.path.abspath(os.path.expanduser(os.environ.get('NUIKIT_RMLUI_DIR') or os.path.join(
        os.environ.get('XDG_CACHE_HOME') or (WINDOWS and os.environ.get('LOCALAPPDATA')) or os.path.expanduser(
            os.path.join('~', '.cache')), 'open77-nui-kit', 'rmlui-' + TAG)))
    os.makedirs(os.path.dirname(d), exist_ok=True)
    memo = os.path.join(os.path.dirname(d), 'compilers.json')
    if a.release:
        return release(a, src, d, memo)
    cc = None
    if os.environ.get('NUIKIT_PREBUILT', '') != '0' and not a.out:
        p = cached_prebuilt(src, d)
        if p:
            print(p)
            return
        cc = find_compiler(memo, required=False)
        if not (cc and os.path.isfile(host_path(cc, src, d))):   # no build of these sources here yet: ask the release
            p, why = fetch_prebuilt(src, d)
            if p:
                print(p)
                return
            if not cc:
                die(f'no prebuilt host ({why}), and none can be built: {find_compiler.why}')
            log(f'no prebuilt host ({why}): building from source')
    cc = cc or find_compiler(memo)
    objdir = os.path.join(d, 'build', 'obj-' + cc.key)
    with Lock(d + '.lock'):
        checkout(d)
        build_core(cc, d, objdir)
    # the host needs no lock: it is linked to a private name, then renamed into place
    if a.out:
        out = os.path.abspath(a.out)
        out += EXE if not out.lower().endswith(EXE) else ''
    else:
        out = host_path(cc, src, d)
    if a.out or not os.path.isfile(out):
        link(cc, src, d, objdir, out, replace=bool(a.out))
    print(out)


if __name__ == '__main__':
    main()
