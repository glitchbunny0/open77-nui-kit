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

# host/common.hpp: the JSON reader
mutant host host/common.hpp "json: an emoji (a surrogate pair) arrives as one 4-byte UTF-8 character" \
    'if (lo >= 0xDC00 && lo < 0xE000) cp =' 'if (false) cp ='
mutant host host/common.hpp "json: the escapes r, b, f and slash decode" \
    "case 'r': out += '\r'; break;" "case 'r': out += 'r'; break;"
mutant host host/common.hpp "json: an unterminated string is an error" \
    'if (p >= e) fail("unterminated string");
			char c' 'if (p >= e) return out;
			char c'
mutant host host/common.hpp "json: a truncated or bad u-escape is an error" \
    'if (e - p < 4) fail("truncated \\u escape");' ''
mutant host host/common.hpp "json: a missing comma or colon is an error" \
    "fail(std::string(\"expected ',' or '\") + close + \"'\");" 'break;'
mutant host host/common.hpp "json: deep nesting is an error, not a stack overflow" \
    'if (++depth > 256) fail("nested deeper than 256");' '++depth;'
mutant host host/common.hpp "json: a bare word is an error" \
    'else fail("unexpected character");' 'else p++;'
mutant host host/common.hpp "json: an integer past int64 is kept as a double" \
    'if (frac || errno == ERANGE)' 'if (frac)'
