"""Maya GLM port, round 15: drop SYCLomatic's use_root_sync launch property (a cooperative launch on Level Zero)
from kernels that never sync the root group.  Usage: fix15.py <raw> <relpath>...  Backs up to <raw>/../pre-fix15/."""
import sys, re, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix15"; bk.mkdir(exist_ok=True)
pat = re.compile(r"sycl::ext::oneapi::experimental::properties\{[\s\\]*sycl::ext::oneapi::experimental::use_root_sync[\s\\]*\}")
for rel in sys.argv[2:]:
    p = raw / rel; s = p.read_text(encoding="utf-8", errors="surrogateescape")
    assert "root_group" not in s, rel
    n = len(pat.findall(s))
    if n == 0: print("  none", rel); continue
    b = bk / rel.replace("/", "__")
    if not b.exists(): shutil.copy(p, b)
    p.write_text(pat.sub("sycl::ext::oneapi::experimental::properties{}", s), encoding="utf-8", errors="surrogateescape")
    print(f"  {n} {rel} left={s.count('use_root_sync') - n}")
