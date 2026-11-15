# The suite's mutants, sourced by tests/host.sh: mutant KIND FILE CHECK OLD NEW (see there). One bug each; the check
# named must go red on its own.

# scripts/build.sh
mutant build scripts/build.sh "build: two host sources sharing one cache dir get their own binaries" \
    'bin="${out:-$dir/build/rmlhost-$hash}"' 'bin="${out:-$dir/build/rmlhost}"'
mutant build scripts/build.sh "build: a build waits while another holds the cache lock" \
    '    flock 9' '    :'
mutant build scripts/build.sh "build: a checkout at another tag is refused" \
    'if [ "$have" != "$tag" ]; then' 'if false; then'
mutant build scripts/build.sh "build: a killed clone leaves no half checkout behind" \
    '"$url" "$dir.tmp.$$"
    mv "$dir.tmp.$$" "$dir"' '"$url" "$dir"'
