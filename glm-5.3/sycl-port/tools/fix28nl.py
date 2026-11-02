import pathlib
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_fast_path.dp.cpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
bad = "cap %d)\r\n\"," if "cap %d)\r\n\"," in t else "cap %d)\n\","
assert t.count(bad) == 1, t.count(bad)
t = t.replace(bad, "cap %d)" + chr(92) + "n\",")
p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("fixed")
