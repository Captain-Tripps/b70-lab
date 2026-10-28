import json, sys, time, urllib.request
# end-to-end check of a llama-swap model: two chat requests, prints wall time, usage and timings, and the answer
base, model = sys.argv[1], sys.argv[2]
prompts = ["Write a Python function that returns the sum of the even numbers in a list, with two pytest tests. Code only.",
           "What is the capital of Australia? Answer in one word."]
for p in prompts:
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": p}], "max_tokens": 300,
                       "temperature": 0}).encode()
    req = urllib.request.Request(base + "/v1/chat/completions", body, {"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=900))
    wall = time.time() - t0
    msg = r["choices"][0]["message"]
    print("wall %.1fs usage %s" % (wall, r.get("usage")))
    if "timings" in r:
        print("timings", {k: r["timings"][k] for k in r["timings"] if "per_second" in k or k.endswith("_n")})
    print("content:", repr((msg.get("content") or "")[:400]))
    print("---")
