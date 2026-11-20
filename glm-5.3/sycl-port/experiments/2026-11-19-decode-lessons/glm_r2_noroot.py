"""GLM r2: drop dpct's use_root_sync from every launch (no kernel in the tree uses a root-group barrier; the ds4 port
gained +1.4% decode from the same change, its fx19). properties{use_root_sync} -> properties{}; any other property
list keeps its other entries. Reports per file; exits non-zero if an occurrence is left.
usage: python glm_r2_noroot.py <tree>/src"""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
RS = r'sycl::ext::oneapi::experimental::use_root_sync'
only = re.compile(r'properties\s*\{(?:\s|\\)*' + RS + r'(?:\s|\\)*\}')
first = re.compile(RS + r'(?:\s|\\)*,(?:\s|\\)*')
last = re.compile(r',(?:\s|\\)*' + RS)
total = 0
left = 0
for p in sorted(list(root.rglob('*.cpp')) + list(root.rglob('*.hpp'))):
    t = p.read_text(encoding='utf-8', errors='surrogateescape')
    if RS not in t:
        continue
    n0 = t.count(RS)
    t2 = only.sub('properties{}', t)
    t2 = first.sub('', t2)
    t2 = last.sub('', t2)
    n1 = t2.count(RS)
    total += n0 - n1
    left += n1
    p.write_text(t2, encoding='utf-8', errors='surrogateescape', newline='')
    print(f'{p.relative_to(root)}: {n0 - n1} removed, {n1} left')
print(f'r2: {total} removed, {left} left')
sys.exit(1 if left else 0)
