import pathlib, sys, re
p = pathlib.Path(sys.argv[1])
t = p.read_text(encoding="utf-8", errors="surrogateescape")
pat = re.compile(r'(\(%p\)|cap %d\))\r?\n"')
n = len(pat.findall(t))
t = pat.sub(lambda m: m.group(1) + chr(92) + 'n"', t)
p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("fixed", n)
