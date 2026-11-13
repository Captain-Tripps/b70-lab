"""Live smoke test of the slot buffer reuse promotion, through llama-swap: a 115k conversation, alternating edits of
its last message (each save after the first two replaces the same conversation's slot, so a spare buffer is free),
a switch to a 7.7k conversation and back."""
import hashlib, json, pathlib, sys, time, urllib.request

out = pathlib.Path(sys.argv[1])
source = pathlib.Path(r'D:\maya-sycl\long_body.txt').read_text(encoding='utf8')
system = {'role': 'system', 'content': 'Be precise.'}
longtext = source[:390000]; shorttext = source[390000:415000]


def messages(text, question):
    return [system, {'role': 'user', 'content': text}, {'role': 'assistant', 'content': 'I have read it.'},
            {'role': 'user', 'content': question}]


def req(label, msgs, max_tokens=64):
    body = {'model': 'glm-5.3-flash-maya-sycl', 'messages': msgs, 'max_tokens': max_tokens, 'temperature': 0,
            'seed': 1, 'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': False}}
    request = urllib.request.Request('http://100.89.126.50:8080/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    t = time.perf_counter(); first = None; usage = None; answer = []
    with urllib.request.urlopen(request, timeout=1800) as response:
        for raw in response:
            line = raw.decode('utf8', 'replace').strip()
            if not line.startswith('data:') or line == 'data: [DONE]':
                continue
            event = json.loads(line[5:].strip()); usage = event.get('usage') or usage
            for ch in event.get('choices', []):
                delta = ch.get('delta') or {}
                part = (delta.get('content') or '') + (delta.get('reasoning_content') or '')
                if part:
                    first = first or time.perf_counter(); answer.append(part)
    row = {'label': label, 'ttft_s': round((first or time.perf_counter()) - t, 3),
           'prompt_tokens': (usage or {}).get('prompt_tokens'),
           'answer_sha256': hashlib.sha256(''.join(answer).encode()).hexdigest()}
    with out.open('a', encoding='utf8') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)


req('health', [{'role': 'user', 'content': 'Reply with the single word READY.'}], 8)
req('long-prime', messages(longtext, 'Give a short status for review 0.'))
for k in range(1, 4):
    req(f'{k}:edit-1', messages(longtext, 'Give a short status for review 1.'))
    req(f'{k}:edit-2', messages(longtext, 'Give a short status for review 2.'))
req('short-switch', messages(shorttext, 'Summarize this briefly.'))
req('long-return', messages(longtext, 'Give a short status for review 2.'))
req('return-edit', messages(longtext, 'Give a short status for review 1.'))
print('SMOKE_DONE', flush=True)
