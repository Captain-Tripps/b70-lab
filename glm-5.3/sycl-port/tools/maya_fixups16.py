"""Maya GLM port, round 16: the IQ2_S / IQ3_S dot products' sign expansion as integer bit tricks instead of
SYCLomatic's byte-vector compare + subtract (dpct::vectorized_binary<uchar4>).  Bit-exact; 1.4x the IQ2_S expert
gate/up kernel in a standalone benchmark (183 -> 129 us a layer).  Backups in <raw>/../pre-fix16/.  Idempotent."""
import sys, re, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix16"; bk.mkdir(exist_ok=True)
pat = re.compile(
    r"const int signs0 = dpct::vectorized_binary<sycl::uchar4>\(\s*\(\(signs_packed_8\[l0 / 2\] & 0x03\) << 7\) \|"
    r"\s*\(\(signs_packed_8\[l0 / 2\] & 0x0C\) << 21\),\s*0x00000000, std::not_equal_to<>\(\)\);"
    r"\s*const int signs1 = dpct::vectorized_binary<sycl::uchar4>\(\s*\(\(signs_packed_8\[l0 / 2\] & 0x30\) << 3\) \|"
    r"\s*\(\(signs_packed_8\[l0 / 2\] & 0xC0\) << 17\),\s*0x00000000, std::not_equal_to<>\(\)\);"
    r"\s*const int grid_l = dpct::vectorized_binary<sycl::uchar4>\(\s*(\S+) \^ signs0, signs0, std::minus<>\(\)\);"
    r"\s*const int grid_h = dpct::vectorized_binary<sycl::uchar4>\(\s*(\S+) \^ signs1, signs1, std::minus<>\(\)\);")
def rep(m):
    return ("// SYCL port (fixups16): 4 sign bits -> 0xFF bytes with one multiply, then a per-byte negate of the grid bytes\n"
            "        // (positive, < 128: never carries across bytes) - not the byte-vector compare + subtract (1.4x)\n"
            "        const uint32_t sgm_ = signs_packed_8[l0 / 2];\n"
            "        const uint32_t sm0_ = (((sgm_ & 0x0Fu) * 0x00204081u) & 0x01010101u) * 0xFFu;\n"
            "        const uint32_t sm1_ = ((((sgm_ >> 4) & 0x0Fu) * 0x00204081u) & 0x01010101u) * 0xFFu;\n"
            f"        const int grid_l = (int) (((uint32_t) ({m.group(1)}) ^ sm0_) + (sm0_ & 0x01010101u));\n"
            f"        const int grid_h = (int) (((uint32_t) ({m.group(2)}) ^ sm1_) + (sm1_ & 0x01010101u));")
for rel in sys.argv[2:]:
    p = raw / rel; s = p.read_text(encoding="utf-8", errors="surrogateescape")
    if "fixups16" in s: print("  already", rel); continue
    b = bk / rel.replace("/", "__")
    if not b.exists(): shutil.copy(p, b)
    s2, n = pat.subn(rep, s)
    p.write_text(s2, encoding="utf-8", errors="surrogateescape")
    print(f"  {n} {rel}, byte-compare sites left {s2.count('0x00000000, std::not_equal_to<>()')}")
