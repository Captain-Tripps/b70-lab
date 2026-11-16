"""dvocab.py - a frequency-ranked MTP draft vocabulary for GLM-5.3 (the pack's tokenizer.json), with held-out coverage.

usage: python dvocab.py <tokenizer_dir> <out_dir> <root> [<root> ...]
Tokenizes the text files under the roots, splits them train/test by a hash of the path (1 in 5 to test), ranks tokens by
train frequency and reports, on the test files, the share of tokens inside each candidate draft vocabulary:
  - the live auto vocabulary (ids below 98304 + digit-only + control/user-defined tokens, as glm_mtp's mtp_vocab_scan),
  - the 32768 id prefix (+ the same extras), the earlier rejected cut,
  - the top-K by frequency (+ the same extras) for several K.
Writes draft_ids_<K>.bin (int32 little-endian, sorted, the extras included) for each K.
"""
import hashlib, json, os, struct, sys, collections
from tokenizers import Tokenizer, Regex, decoders, models, pre_tokenizers

EXT = {'.c', '.cc', '.cpp', '.cu', '.h', '.hpp', '.cuh', '.py', '.md', '.txt', '.sh', '.ps1', '.js', '.ts', '.html', '.css',
       '.cmake', '.json', '.toml', '.yaml', '.yml', '.jinja', '.rs', '.go', '.java', '.swift', '.kt', '.glsl', '.comp',
       '.metal', '.m', '.mm', '.bat', '.cmd', '.ini'}
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', 'build', 'models', 'venv', '.venv'}


def files(roots):
    for r in roots:
        for dp, dn, fn in os.walk(r):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            for f in fn:
                p = os.path.join(dp, f)
                if os.path.splitext(f)[1].lower() in EXT and 0 < os.path.getsize(p) < 2_000_000:
                    yield p


def token_kind(s):
    ascii_ok = digits = bool(s)
    for ch in s:
        c = ord(ch)
        if not ((0x21 <= c <= 0x7E) or (0x100 <= c <= 0x121)): ascii_ok = False
        if not ('0' <= ch <= '9'): digits = False
    return ascii_ok, digits


def main():
    tdir, out, roots = sys.argv[1], sys.argv[2], sys.argv[3:]
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(tdir, 'tokenizer.json'), encoding='utf-8'))
    vocab = json.load(open(os.path.join(tdir, 'vocab.json'), encoding='utf-8'))
    merges = []
    with open(os.path.join(tdir, 'merges.txt'), encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if line and not line.startswith('#version'):
                a, b = line.split(' ', 1)
                merges.append((a, b))
    bpe = models.BPE(vocab=vocab, merges=merges, ignore_merges=bool(meta.get('ignore_merges', False)))
    tok = Tokenizer(bpe)
    tok.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(meta['pre_pattern']), behavior='isolated'),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)])
    tok.decoder = decoders.ByteLevel()
    N = int(meta['vocab_size'])
    id2s = [''] * N
    for s, i in vocab.items():
        if i < N: id2s[i] = s
    types = json.load(open(os.path.join(tdir, 'token_type.json'), encoding='utf-8'))
    special = {i for i, t in enumerate(types) if t in (3, 4)}
    probe = 'def f(x):\n    return x**2  # The quick brown fox, 12345 tokens.\n\nShe said, "It\'s over."'
    ids = tok.encode(probe, add_special_tokens=False).ids
    print(f'roundtrip ok: {tok.decode(ids) == probe} ({len(ids)} tokens)')
    digit_ids = {i for i in range(N) if id2s[i] and token_kind(id2s[i])[1]}
    extras = special | digit_ids
    print(f'vocab {N}, special/added {len(special)}, digit-only {len(digit_ids)}')

    train, test = collections.Counter(), collections.Counter()
    nfiles = [0, 0]
    texts = []
    for p in files(roots):
        try:
            t = open(p, encoding='utf-8').read()
        except (UnicodeDecodeError, OSError):
            continue
        h = int(hashlib.sha1(p.encode()).hexdigest(), 16) % 5
        texts.append((h == 0, t))
    B = 256
    for k in range(0, len(texts), B):
        chunk = texts[k:k + B]
        encs = tok.encode_batch([t for _, t in chunk], add_special_tokens=False)
        for (is_test, _), e in zip(chunk, encs):
            (test if is_test else train).update(e.ids)
            nfiles[is_test] += 1
    nt, ne = sum(train.values()), sum(test.values())
    print(f'train {nfiles[0]} files {nt:,} tokens; test {nfiles[1]} files {ne:,} tokens; distinct train ids {len(train):,}')

    def cover(vset):
        return sum(c for i, c in test.items() if i in vset) / ne

    auto = set(range(98304)) | extras
    pre32 = set(range(32768)) | extras
    print(f'{"vocabulary":34s} {"rows":>7s} {"MB/draft":>8s} {"test coverage":>14s} {"misses per 1k":>14s}')
    rb = 3360  # Q6_K row of 4096
    def row(name, v):
        c = cover(v)
        print(f'{name:34s} {len(v):7d} {len(v) * rb / 1048576:8.0f} {100 * c:13.3f}% {1000 * (1 - c):14.2f}')
    row('live auto (ids<98304 + extras)', auto)
    row('id prefix 32768 + extras', pre32)
    ranked = [i for i, _ in train.most_common()]
    for K in (8192, 16384, 24576, 32768, 40960, 49152):
        v = set(ranked[:K]) | extras
        row(f'top {K} by frequency + extras', v)
        ids = sorted(v)
        with open(os.path.join(out, f'draft_ids_{K}.bin'), 'wb') as f:
            f.write(struct.pack(f'<{len(ids)}i', *ids))
    # how far into the id space the frequent tokens reach
    for K in (16384, 32768):
        v = set(ranked[:K])
        print(f'top {K}: {sum(1 for i in v if i >= 98304)} ids >= 98304, {sum(1 for i in v if i < 32768)} below 32768, '
              f'longest covered id prefix {next((j for j in range(N) if j not in (v | extras)), N)}')


if __name__ == '__main__':
    main()
