import json, sys
sys.path.insert(0, r"<work>\maya\tools")
from strata_tokenizer import Tokenizer
d = r"<work>\glm-m\pack\tokenizer"
v = json.load(open(d + r"\vocab.json", encoding="utf-8"))
toks = [None] * len(v)
for t, i in v.items(): toks[i] = t
merges = [l.rstrip("\n") for l in open(d + r"\merges.txt", encoding="utf-8") if l.strip() and not l.startswith("#")]
tt = json.load(open(d + r"\token_type.json", encoding="utf-8"))
tt = tt if isinstance(tt, list) else tt.get("token_type", None)
tk = Tokenizer(toks, merges, tt, pre="glm5")
mode = sys.argv[1]
if mode == "enc":
    print(",".join(str(i) for i in tk.encode(sys.argv[2])))
else:
    ids = [int(x) for x in sys.argv[2].split(",") if x]
    print(repr("".join(toks[i] for i in ids)))
