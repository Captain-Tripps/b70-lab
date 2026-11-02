"""Maya GLM port, round 27: immediate command lists on the Level Zero v1 adapter.  fixups24 moved generate to the v1
adapter (the v2 adapter deadlocks under the overlapped hop); v1 defaults to batched regular command lists on Windows,
which cost the batched prefill ~14% (8k prompt: 617 tok/s on v1 vs 704 on v2) and nothing in decode.
UR_L0_USE_IMMEDIATE_COMMANDLISTS=1 on v1: prefill 704 tok/s, decode the same.  So generate sets it at static init, like
SYCL_UR_USE_LEVEL_ZERO_V2=0, unless the caller set it.  Backups in <raw>/../pre-fix27/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix27"; bk.mkdir(exist_ok=True)
p = raw / "src/core/glm_fast_path.dp.cpp"
t = p.read_text(encoding="utf-8", errors="surrogateescape")
old = """    if (std::getenv("SYCL_UR_USE_LEVEL_ZERO_V2") == nullptr) {
#ifdef _WIN32
        _putenv_s("SYCL_UR_USE_LEVEL_ZERO_V2", "0");
#else
        setenv("SYCL_UR_USE_LEVEL_ZERO_V2", "0", 0);
#endif
    }
    return 0;"""
new = """    if (std::getenv("SYCL_UR_USE_LEVEL_ZERO_V2") == nullptr) {
#ifdef _WIN32
        _putenv_s("SYCL_UR_USE_LEVEL_ZERO_V2", "0");
#else
        setenv("SYCL_UR_USE_LEVEL_ZERO_V2", "0", 0);
#endif
    }
    // SYCL port (fixups27): v1's batched regular command lists cost the batched prefill ~14%; immediate lists do not
    if (std::getenv("UR_L0_USE_IMMEDIATE_COMMANDLISTS") == nullptr) {
#ifdef _WIN32
        _putenv_s("UR_L0_USE_IMMEDIATE_COMMANDLISTS", "1");
#else
        setenv("UR_L0_USE_IMMEDIATE_COMMANDLISTS", "1", 0);
#endif
    }
    return 0;"""
if "fixups27" not in t:
    assert t.count(old) == 1, t.count(old)
    shutil.copy(p, bk / "glm_fast_path.dp.cpp")
    p.write_text(t.replace(old, new), encoding="utf-8", errors="surrogateescape"); print("  v1 immediate command lists by default")
else: print("  already")
