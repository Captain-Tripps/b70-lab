from gguf import GGUFReader
import collections
p='<atlas-home>/models/qwen3.8-27b-abliterated/Huihui-Qwen3.8-27B-abliterated-UD-Q4_K_XL.gguf'
r=GGUFReader(p)
for t in r.tensors:
    if str(t.tensor_type).endswith('IQ4_NL') or t.tensor_type.name == 'IQ4_NL':
        print(t.name, list(t.shape), t.tensor_type.name, t.n_bytes)
