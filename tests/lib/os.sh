# Sourced by the suites: what differs between Linux, macOS (bash 3.2, BSD tools) and Windows (Git Bash).
#   windows      1 under Git Bash / MSYS on Windows, else 0
#   py           the Python 3 to run: $PYTHON, else python3, else python
#   shim FILE    the path to run the shell script FILE as a program: FILE itself on Linux and macOS (made executable);
#                on Windows FILE.cmd, written next to it, which runs FILE with this bash (Windows starts no program by
#                its #! line, and Python's subprocess starts only .exe and .cmd files)
#   upath PATH   PATH as this shell writes paths (a native Windows program prints C:\...; elsewhere PATH as is)
case "$(uname -s 2>/dev/null)" in MINGW* | MSYS* | CYGWIN*) windows=1 ;; *) windows=0 ;; esac
py="${PYTHON:-}"
[ -n "$py" ] || py=$(command -v python3 || command -v python)
shim() {
    if [ "$windows" = 1 ]; then
        printf '@"%s" "%s" %%*\r\n' "$(cygpath -w "$BASH")" "$(cygpath -w "$1")" > "$1.cmd"
        echo "$1.cmd"
    else
        chmod +x "$1"
        echo "$1"
    fi
}
upath() { if [ "$windows" = 1 ]; then cygpath -u "$1"; else printf '%s\n' "$1"; fi; }
# plant SRC DST OLD NEW: writes DST, SRC with OLD (it must occur exactly once) replaced by NEW, byte for byte otherwise;
# else prints how often OLD occurs and fails. OLD and NEW go to Python in files: Git Bash rewrites an argument or an
# environment value that looks like a path ("$KIT"/bin/x became "$KIT"C:/Program Files/Git/usr/bin/x)
plant() {
    printf '%s' "$3" > "$2.old"; printf '%s' "$4" > "$2.new"
    "$py" - "$1" "$2" <<'PY'
import sys
src, dst = sys.argv[1:3]
old, new = (open(dst + ext, encoding='utf-8', newline='').read() for ext in ('.old', '.new'))
s = open(src, encoding='utf-8', newline='').read()
if s.count(old) != 1:
    print('mutant site matches %d times: %r' % (s.count(old), old[:70]))
    sys.exit(1)
open(dst, 'w', encoding='utf-8', newline='').write(s.replace(old, new))
PY
    local rc=$?
    rm -f "$2.old" "$2.new"
    return $rc
}
