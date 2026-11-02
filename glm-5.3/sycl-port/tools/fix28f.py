import pathlib, re
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_fast_path.dp.cpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
pat = re.compile(r"F->cs->memcpy\(restore \? live : bak, restore \? bak : live,\s*run \* sizeof\(float\)\);")
assert len(pat.findall(t)) == 1, len(pat.findall(t))
t = pat.sub("maya_kcopy(F->cs, restore ? live : bak, restore ? bak : live, run * sizeof(float));   // SYCL port (fixups28): a queue memcpy behind a graph replay never completes (L0 v1)", t)
p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("kda backup via kcopy")
