import json, sys, time, urllib.request

base = 'http://100.89.126.50:8080'
system = {'role': 'system', 'content': 'You are a concise lab assistant.'}
longtext = ' '.join(f'Line {i}: sensor {i % 17} read {(i * 37) % 1000} units at step {i}.' for i in range(1400))
shorttext = 'The quick check passed on all four cards and the queue is empty.'


def messages(text, question):
    return [system, {'role': 'user', 'content': text}, {'role': 'assistant', 'content': 'I have read it.'},
            {'role': 'user', 'content': question}]


def req(label, msgs, max_tokens=64):
    body = {'model': 'glm-5.3-flash-maya-sycl', 'messages': msgs, 'max_tokens': max_tokens, 'temperature': 0,
            'seed': 1, 'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': False}}
    request = urllib.request.Request(base + '/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    t0 = time.perf_counter(); first = None; answer = []; usage = {}
    with urllib.request.urlopen(request, timeout=1800) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith('data:') or line == 'data: [DONE]':
                continue
            chunk = json.loads(line[5:])
            usage = chunk.get('usage') or usage
            for choice in chunk.get('choices', []):
                delta = choice.get('delta', {})
                part = (delta.get('content') or '') + (delta.get('reasoning_content') or '')
                if part:
                    first = first or time.perf_counter(); answer.append(part)
    text = ''.join(answer)
    print(json.dumps({'label': label, 'ttft_s': round((first or time.perf_counter()) - t0, 3),
                      'elapsed_s': round(time.perf_counter() - t0, 3), 'prompt_tokens': usage.get('prompt_tokens'),
                      'answer': text[:80]}), flush=True)
    return text


req('health', [{'role': 'user', 'content': 'Reply with the single word READY.'}], 8)
a1 = req('A-prime', messages(longtext, 'Give a short status for review 1.'))
req('B-switch', messages(shorttext, 'Summarize this briefly.'))
a2 = req('A-new-text-edit', messages(longtext, 'Give a short status for review 2.'))
req('B-switch-2', messages(shorttext, 'Summarize this briefly.'))
a1b = req('A-repeat-1', messages(longtext, 'Give a short status for review 1.'))
print('A repeat matches prime:', a1 == a1b)
