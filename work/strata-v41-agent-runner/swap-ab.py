import json, sys, time, uuid, urllib.request, statistics
# same-day A/B of llama-swap models: fixed prompt set, every request cold (unique first line), temperature 0.
# usage: swap-ab.py BASE_URL OUT.jsonl model1 [model2 ...]   (each model: one load request, then REPS rounds)
REPS = 3
PROMPTS = {
    "code": "Write a Python function that parses an ISO 8601 date string without using datetime.fromisoformat, with three pytest tests.",
    "prose": "Write the opening two paragraphs of a mystery story set in a lighthouse during a storm.",
    "explain": "Explain how a hash table handles collisions, comparing chaining and open addressing, in about 200 words.",
    "summary": "Summarize the causes and main events of the French Revolution in eight bullet points.",
}
base, out_path, models = sys.argv[1], sys.argv[2], sys.argv[3:]
out = open(out_path, "a", encoding="utf-8")


def ask(model, text, max_tokens):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": text}], "max_tokens": max_tokens,
                       "temperature": 0, "cache_prompt": False, "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(base + "/v1/chat/completions", body, {"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    return r, time.time() - t0


for m in models:
    r, w = ask(m, "Say OK.", 8)   # load the model; not measured
    print("%s loaded in %.1f s" % (m, w), flush=True)
    rates = []
    for rep in range(REPS):
        for name, p in PROMPTS.items():
            text = "[request %s]\n%s" % (uuid.uuid4().hex[:12], p)
            r, w = ask(m, text, 400)
            t = r.get("timings", {})
            u = r.get("usage", {})
            c = r["choices"][0]["message"]
            rec = {"model": m, "rep": rep + 1, "prompt": name, "wall_s": round(w, 2),
                   "completion_tokens": u.get("completion_tokens"), "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                   "tg": t.get("predicted_per_second"), "pp": t.get("prompt_per_second"), "draft_n": t.get("draft_n"),
                   "draft_accepted": t.get("draft_n_accepted"), "finish": r["choices"][0].get("finish_reason"),
                   "content_head": (c.get("content") or "")[:160], "reasoning_len": len(c.get("reasoning_content") or "")}
            out.write(json.dumps(rec) + "\n"); out.flush()
            if rec["tg"]:
                rates.append(rec["tg"])
            print("%s r%d %-8s tg=%s pp=%s n=%s cached=%s wall=%.1f" % (m, rep + 1, name, rec["tg"], rec["pp"],
                  rec["completion_tokens"], rec["cached"], w), flush=True)
    if rates:
        print("== %s decode median %.2f (min %.2f max %.2f, n=%d)" % (m, statistics.median(rates), min(rates), max(rates), len(rates)), flush=True)
