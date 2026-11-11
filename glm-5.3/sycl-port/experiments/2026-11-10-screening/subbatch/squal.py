"""Full answers to the checkable prompts (temperature 0, thinking off), non-streamed. usage: squal.py URL MODEL"""
import json, sys, urllib.request
url, model = sys.argv[1], sys.argv[2]
qs = {
    "json": "Extract a JSON array of objects with fields name, role, start_date from the text: Priya Natarajan joined as head of data on 2021-03-15, replacing Tom Eriksen who moved to the London office in the same month. Wei Zhang started as a staff engineer on 2022-07-01 and Fatima Al-Sayed became the CFO on 2020-11-09. Output only JSON.",
    "math": "A warehouse ships 340 boxes per day on weekdays and 120 per day on Saturdays, nothing on Sundays. A 12 percent damage rate applies to Saturday shipments only. How many undamaged boxes ship in 5 full weeks? Give only the final number.",
    "capital": "List the capitals of France, Japan, Brazil, Kenya and Canada, comma-separated, nothing else.",
    "count": "Count from 1 to 30, separated by commas, nothing else.",
}
for k, q in qs.items():
    body = {"model": model, "messages": [{"role": "user", "content": q}], "max_tokens": 300, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=600))
    print(f"--- {k}: {' '.join(r['choices'][0]['message']['content'].split())[:600]}", flush=True)
