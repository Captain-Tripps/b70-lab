"""Engine-agnostic OpenAI-API bench: a fixed 7-prompt set, streamed, temperature 0, thinking off.
decode tok/s = (completion tokens - 1) / (last token time - first token time); prompt tok/s from a long read.
usage: python sbench.py URL MODEL [--n 512] [--rounds 2] [--long 30000] [--tag name] [--doc file]"""
import argparse, json, sys, time, urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("url"); ap.add_argument("model")
ap.add_argument("--n", type=int, default=512); ap.add_argument("--rounds", type=int, default=2)
ap.add_argument("--long", type=int, default=30000, help="approx prompt tokens for the read test (0: skip)")
ap.add_argument("--tag", default="")
ap.add_argument("--doc", default=__file__, help="text file used for the code-explain prompt and the long read")
a = ap.parse_args()

src = Path(a.doc).read_text(encoding="utf-8", errors="replace")
doc = "Here is the first part of a source file:\n\n" + src[:2000] + "\n\n=== END OF EXCERPT ===\n"
prose = ("From: Dana Whitfield. Subject: Q3 vendor consolidation. Team, after three weeks of review we have narrowed the field from nine "
         "logistics vendors to three. Northbridge offers the lowest per-pallet cost (14.20 dollars) but only guarantees 72-hour delivery "
         "windows in the Midwest. Caliber Freight is 11 percent more expensive but offers two-day delivery nationwide and has an API we can "
         "integrate with our warehouse system by November. Sable Transport is the cheapest for cold-chain at 22 dollars per pallet but has "
         "had two reported temperature excursions this year. Finance wants a decision by the 24th because the current contract with Harlow "
         "expires on the 31st and renewal carries a 9 percent penalty. Legal flagged that Northbridge's liability cap is only 50,000 dollars "
         "per incident, which is below our insurance minimum. Operations prefers Caliber for the integration but worries about onboarding "
         "capacity during the holiday peak. Please reply with your vote and any blocking concerns by Friday noon.")
passage = ("Mara tightened the strap on her left boot and watched the ridge line. It was dawn on the third day since the supply drop, and the "
           "rations were down to two tins of beans. Her brother Eli, who had left two days ago at dusk to scout the valley, still had not "
           "returned. She remembered his last words clearly: he would be back by the next sunrise, which made today the first morning he was "
           "late. At noon she climbed down to the stream and counted her four remaining flares, then lit one. By evening, on the fourth day, "
           "a figure appeared on the ridge, limping, carrying the rifle he had promised to leave with her. Eli grinned and said he had walked "
           "all night without stopping, though he had also slept in the cave by the falls.")
js = ("Extract a JSON array of objects with fields name, role, start_date from the text: Priya Natarajan joined as head of data on "
      "2021-03-15, replacing Tom Eriksen who moved to the London office in the same month. Wei Zhang started as a staff engineer on "
      "2022-07-01 and Fatima Al-Sayed became the CFO on 2020-11-09. Output only JSON.")
prompts = [
    ("code-explain", doc + "Explain in about 150 words what the last complete function shown above does."),
    ("code-write", "Write a Python function that parses ISO 8601 durations such as P1DT2H30M into total seconds, handling years and months as 365 and 30 days, with three pytest tests. Keep it compact."),
    ("prose-summary", "Summarize this email thread in five bullet points and state the decision needed.\n\n" + prose),
    ("fiction", "Write the opening 250 words of a short story about a lighthouse keeper who finds that the light has been switched on every night by someone else. Close third person, past tense, concrete detail."),
    ("json-extract", js),
    ("edit-continuity", "You are a continuity editor. List every continuity or timeline error in this passage with a short quote for each.\n\n" + passage),
    ("reasoning", "A warehouse ships 340 boxes per day on weekdays and 120 per day on Saturdays, nothing on Sundays. A 12 percent damage rate applies to Saturday shipments only. How many undamaged boxes ship in 5 full weeks? Show the arithmetic step by step."),
]


def ask(content, n):
    body = {"model": a.model, "messages": [{"role": "user", "content": content}], "max_tokens": n, "temperature": 0,
            "seed": 1, "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(a.url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter(); first = last = None; chunks = 0; text = []; usage = None
    with urllib.request.urlopen(req, timeout=3600) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            ev = json.loads(data)
            if ev.get("usage"):
                usage = ev["usage"]
            for ch in ev.get("choices") or []:
                d = (ch.get("delta") or {})
                piece = (d.get("content") or "") + (d.get("reasoning_content") or "")
                if piece:
                    now = time.perf_counter()
                    first = first or now; last = now; chunks += 1; text.append(piece)
    ntok = (usage or {}).get("completion_tokens") or chunks
    ptok = (usage or {}).get("prompt_tokens")
    ttft = (first - t0) if first else float("nan")
    dec = (ntok - 1) / (last - first) if first and last and last > first else float("nan")
    return ntok, ptok, ttft, dec, "".join(text)


print(f"=== {a.tag or a.model} @ {a.url}  n={a.n} rounds={a.rounds}  {time.strftime('%H:%M:%S')}", flush=True)
rates = {}
for rnd in range(1, a.rounds + 1):
    for name, p in prompts:
        ntok, ptok, ttft, dec, txt = ask(p, a.n)
        rates.setdefault(name, []).append(dec)
        snip = " ".join(txt.split())[:70]
        print(f"r{rnd} {name:16s} prompt={ptok} gen={ntok:4d} ttft={ttft:6.2f}s decode={dec:6.1f} tok/s  '{snip}'", flush=True)
allr = [x for v in rates.values() for x in v[1:] or v]   # round 1 is warm-up when there are 2+
print(f"mean decode (rounds 2+): {sum(allr) / len(allr):.1f} tok/s over {len(allr)} replies", flush=True)
if a.long:
    filler = (src * 40)[: a.long * 4]   # ~4 chars per token
    ntok, ptok, ttft, dec, _ = ask("Here is a long file:\n\n" + filler + "\n\nIn one sentence: what is this file about?", 32)
    print(f"long read: prompt={ptok} ttft={ttft:.1f}s -> {(ptok or 0) / ttft:.0f} tok/s prompt; decode after it {dec:.1f} tok/s", flush=True)
