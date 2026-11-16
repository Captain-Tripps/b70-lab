import sys
sys.path.insert(0, r'<work>\maya\tools')
import strata_tokenizer as ST
t = ST.Tokenizer.from_dir(r'<work>\glm-m\pack\tokenizer')
ids = list(t.encode(open(r'<work>\long_body.txt', encoding='utf8').read()))[:115072]
open(r'<work>\long115k.txt', 'w').write(','.join(map(str, ids)) + ',')
print('tokens', len(ids), ids[:5])
