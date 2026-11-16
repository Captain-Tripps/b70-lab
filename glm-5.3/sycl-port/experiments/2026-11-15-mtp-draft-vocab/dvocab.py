"""dvocab.py - a frequency-ranked MTP draft vocabulary for GLM-5.3 (the pack's tokenizer files), with held-out coverage.

usage: python dvocab.py <tokenizer_dir> <out_dir> <label>=<root>[,<root>...] [<label>=<root>...]
Tokenizes the text files under each labelled corpus, splits files train/test by a hash of the path (1 in 5 to test),
ranks tokens by train frequency - each corpus weighted equally (its counts divided by its token total) - and reports,
per corpus on its test files, the share of tokens inside each candidate draft vocabulary:
  - the live auto vocabulary (ids below 98304 + digit-only + control/user-defined tokens, as glm_mtp's mtp_vocab_scan),
  - the 32768 id prefix (+ the same extras), the earlier rejected cut,
  - the top-K by frequency (+ the same extras) for several K.
Writes draft_ids_<K>.bin (int32 little-endian, sorted, the extras included) for each K.
"""
import collections, hashlib, json, os, struct, sys
from tokenizers import Tokenizer, Regex, decoders, models, pre_tokenizers

EXT = {'.c', '.cc', '.cpp', '.cu', '.h', '.hpp', '.cuh', '.py', '.md', '.txt', '.sh', '.ps1', '.js', '.ts', '.html', '.css',
       '.cmake', '.json', '.toml', '.yaml', '.yml', '.jinja', '.rs', '.go', '.java', '.swift', '.kt', '.glsl', '.comp',
       '.metal', '.m', '.mm', '.bat', '.cmd', '.ini'}
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', 'build', 'models', 'venv', '.venv'}
KS = (16384, 24576, 32768, 40960, 49152)


def files(roots):
    for r in roots:
        for dp, dn, fn in os.walk(r):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            for f in fn:
                p = os.path.join(dp, f)
                if os.path.splitext(f)[1].lower() in EXT and 0 < os.path.getsize(p) < 2_000_000:
                    yield p


def is_digits(s):
    return bool(s) and all('0' <= ch <= '9' for ch in s)


def load_tokenizer(tdir):
    meta = json.load(open(os.path.join(tdir, 'tokenizer.json'), encoding='utf-8'))
    vocab = json.load(open(os.path.join(tdir, 'vocab.json'), encoding='utf-8'))
    merges = []
    with open(os.path.join(tdir, 'merges.txt'), encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if line and not line.startswith('#version'):
                a, b = line.split(' ', 1)
                merges.append((a, b))
    tok = Tokenizer(models.BPE(vocab=vocab, merges=merges, ignore_merges=bool(meta.get('ignore_merges', False))))
    tok.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(meta['pre_pattern']), behavior='isolated'),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)])
    tok.decoder = decoders.ByteLevel()
    N = int(meta['vocab_size'])
    id2s = [''] * N
    for s, i in vocab.items():
        if i < N: id2s[i] = s
    types = json.load(open(os.path.join(tdir, 'token_type.json'), encoding='utf-8'))
    return tok, N, id2s, {i for i, t in enumerate(types) if t in (3, 4)}


def main():
    tdir, out, specs = sys.argv[1], sys.argv[2], sys.argv[3:]
    os.makedirs(out, exist_ok=True)
    tok, N, id2s, special = load_tokenizer(tdir)
    probe = 'def f(x):\n    return x**2  # The quick brown fox, 12345 tokens.\n\nShe said, "It\'s over."'
    ids = tok.encode(probe, add_special_tokens=False).ids
    print(f'roundtrip ok: {tok.decode(ids) == probe} ({len(ids)} tokens)')
    extras = special | {i for i in range(N) if is_digits(id2s[i])}
    print(f'vocab {N}, control/user-defined {len(special)}, extras {len(extras)}')

    corpora = {}
    for spec in specs:
        label, roots = spec.split('=', 1)
        train, test = collections.Counter(), collections.Counter()
        texts, nf = [], [0, 0]
        for p in files(roots.split(',')):
            try:
                t = open(p, encoding='utf-8').read()
            except (UnicodeDecodeError, OSError):
                continue
            texts.append((int(hashlib.sha1(p.encode()).hexdigest(), 16) % 5 == 0, t))
        for k in range(0, len(texts), 256):
            chunk = texts[k:k + 256]
            for (is_test, _), e in zip(chunk, tok.encode_batch([t for _, t in chunk], add_special_tokens=False)):
                (test if is_test else train).update(e.ids)
                nf[is_test] += 1
        corpora[label] = (train, test)
        print(f'{label}: train {nf[0]} files {sum(train.values()):,} tokens; test {nf[1]} files '
              f'{sum(test.values()):,} tokens; distinct train ids {len(train):,}')

    score = collections.Counter()
    for train, _ in corpora.values():
        tot = sum(train.values())
        for i, c in train.items():
            score[i] += c / tot
    ranked = [i for i, _ in score.most_common()]

    rb = 3360  # Q6_K row of 4096
    vocabs = [('live auto (ids<98304 + extras)', set(range(98304)) | extras),
              ('id prefix 32768 + extras', set(range(32768)) | extras)]
    for K in KS:
        v = set(ranked[:K]) | extras
        vocabs.append((f'top {K} by frequency + extras', v))
        sorted_ids = sorted(v)
        with open(os.path.join(out, f'draft_ids_{K}.bin'), 'wb') as f:
            f.write(struct.pack(f'<{len(sorted_ids)}i', *sorted_ids))
    labels = list(corpora)
    print(f'\n{"vocabulary":34s} {"rows":>7s} {"MB/draft":>8s}  ' + '  '.join(f'{l + " miss/1k":>16s}' for l in labels))
    for name, v in vocabs:
        cells = []
        for l in labels:
            test = corpora[l][1]
            n = sum(test.values())
            cells.append(f'{1000 * sum(c for i, c in test.items() if i not in v) / n:16.2f}')
        print(f'{name:34s} {len(v):7d} {len(v) * rb / 1048576:8.0f}  ' + '  '.join(cells))
    v = set(ranked[:32768])
    print(f'\ntop 32768: {sum(1 for i in v if i >= 98304)} ids >= 98304, {sum(1 for i in v if i < 32768)} below 32768')


if __name__ == '__main__':
    main()
