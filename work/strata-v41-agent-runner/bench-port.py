import json, urllib.request, time, sys

PORT = sys.argv[1] if len(sys.argv) > 1 else '9100'
BASE = 'http://127.0.0.1:' + PORT

def post(payload, timeout=3000):
    req = urllib.request.Request(BASE + '/v1/chat/completions',
                                data=json.dumps(payload).encode(),
                                headers={'Content-Type': 'application/json'})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0

def show(tag, body, dt):
    tim = body.get('timings', {}) or {}
    usage = body.get('usage', {}) or {}
    ch = (body.get('choices') or [{}])[0]
    print('%s: wall=%.1fs prompt_tokens=%s completion=%s prefill=%.3f tok/s decode=%.3f tok/s finish=%s' % (
        tag, dt, usage.get('prompt_tokens'), usage.get('completion_tokens'),
        tim.get('prompt_per_second', 0) or 0, tim.get('predicted_per_second', 0) or 0,
        ch.get('finish_reason')), flush=True)
    msg = ch.get('message', {}) or {}
    print('   content=%r' % ((msg.get('content', '') or '')[:200]), flush=True)
    if msg.get('reasoning_content'):
        print('   reasoning=%r' % msg['reasoning_content'][:200], flush=True)

def run(tag, payload):
    try:
        b, dt = post(payload)
        show(tag, b, dt)
    except Exception as e:
        print('%s FAILED: %s' % (tag, e), flush=True)

# 1. end-to-end check with minimal work
run('TINY (1 token)', {'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 1,
                       'temperature': 0, 'stream': False})
# 2. prefill number
para = 'The quick brown fox jumps over the lazy dog. ' * 15
run('~160 token prompt', {'messages': [{'role': 'user', 'content': para + ' Reply with only: DONE'}],
                          'max_tokens': 4, 'temperature': 0, 'stream': False})
# 3. decode number + coherence (thinking off so the tokens are visible)
dec = {'messages': [{'role': 'user', 'content': 'Write a short paragraph about the history of the printing press.'}],
       'max_tokens': 128, 'temperature': 0, 'stream': False,
       'chat_template_kwargs': {'enable_thinking': False}}
run('decode 128', dec)
# 4. optional warm pass: same requests again once JIT and page cache are warm
if '--warm' in sys.argv:
    run('WARM ~160 token prompt', {'messages': [{'role': 'user', 'content': 'Different text. ' + para + ' Reply with only: OK'}],
                                   'max_tokens': 4, 'temperature': 0, 'stream': False})
    run('WARM decode 128', dict(dec, messages=[{'role': 'user', 'content': 'Write a short paragraph about the history of the steam engine.'}]))
