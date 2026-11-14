import json, time, urllib.request, sys
n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
body = {'model': 'glm-5.3-flash-maya-sycl', 'messages': [{'role': 'user', 'content': 'Write a long, detailed technical essay on the history of the printing press, at least 3000 words.'}],
        'max_tokens': n, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}}
t = time.perf_counter(); print('START', time.strftime('%H:%M:%S'), flush=True)
r = json.load(urllib.request.urlopen(urllib.request.Request('<proxy>/v1/chat/completions', json.dumps(body).encode(), {'Content-Type': 'application/json'}), timeout=900))
tm = r.get('timings', {})
print('END', time.strftime('%H:%M:%S'), 'wall', round(time.perf_counter() - t, 1), 'gen_n', tm.get('predicted_n'), 'gen_tps', tm.get('predicted_per_second'), 'draft', tm.get('draft_n'), tm.get('draft_n_accepted'), flush=True)
