import pathlib

# Focused count-limit fairness A/B. B is revisited before any other B-derived prompt.
base=pathlib.Path(__file__).with_name('broad_ab.py')
source=base.read_text(encoding='utf8')
source=source.replace('codex-slot-branch-broad-20261112','codex-slot-branch-fairness-20261112')
source=source.replace("  req('independent-long',msgs(long2,'Summarize this in one sentence.'))\n  req('B-revisit',b);req('B-repeat',b)", "  req('B-revisit',b);req('B-repeat',b)\n  req('independent-long',msgs(source[200000:230000],'Summarize this in one sentence.'))")
source=source.replace("  # Real tool-call payload and round trip:", "  # Real tool-call payload and round trip:")
exec(compile(source,str(base),'exec'))
