"""Port upstream Maya's MAYA_TURN_TRACE server marks (c25b1dbf) into an isolated copy of the live v1.1.44 server.
Server only, off unless MAYA_TURN_TRACE is set in the server's own environment. Each anchor must match exactly once."""
import hashlib, sys
from pathlib import Path

p = Path(sys.argv[1])
raw = p.read_bytes()
LIVE = "76185526a58aa06193233b0d9d0f8b7282e6ce888b31004be9cad6dc3140971f"
if hashlib.sha256(raw).hexdigest() != LIVE:
    sys.exit("not the live server.py")
s = raw.decode("utf-8")
NL = "\r\n"


def sub(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        sys.exit(f"anchor matched {n} times, wanted {count}: {old[:80]!r}")
    s = s.replace(old, new)


def ln(*lines):
    return NL.join(lines)


sub(ln("class Engine(Protocol):"),
    ln("TURN_TRACE = os.environ.get(\"MAYA_TURN_TRACE\", \"\") not in (\"\", \"0\")",
       "TURN = {}",
       "",
       "",
       "def turn_mark(name: str) -> None:",
       "    if TURN_TRACE:",
       "        TURN[name] = time.monotonic() * 1000.0",
       "",
       "",
       "def turn_print(n=None) -> None:",
       "    if TURN_TRACE and TURN:",
       "        t0 = TURN.get(\"http\", min(TURN.values()))",
       "        print(\"[maya] trace n=%s \" % n + \" \".join(f\"{k}={v - t0:.1f}\" for k, v in sorted(TURN.items(), key=lambda x: x[1])) +",
       "              f\" t0={t0:.1f}\", flush=True)",
       "        TURN.clear()",
       "",
       "",
       "class Engine(Protocol):"))

# single-conversation engine path
sub(ln("        try:",
       "            self.proc.stdin.write(f\"{head} {','.join(str(int(t)) for t in ids)}\\n\")",
       "            self.proc.stdin.flush()"),
    ln("        try:",
       "            turn_mark(\"gen_start\")",
       "            self.proc.stdin.write(f\"{head} {','.join(str(int(t)) for t in ids)}\\n\")",
       "            turn_mark(\"gen_written\")",
       "            self.proc.stdin.flush()",
       "            turn_mark(\"gen_flushed\")"))
# several-conversation engine path
sub(ln("            try:",
       "                self.proc.stdin.write(f\"{head} {','.join(str(int(t)) for t in ids)}\\n\")",
       "                self.proc.stdin.flush()"),
    ln("            try:",
       "                turn_mark(\"gen_start\")",
       "                self.proc.stdin.write(f\"{head} {','.join(str(int(t)) for t in ids)}\\n\")",
       "                turn_mark(\"gen_written\")",
       "                self.proc.stdin.flush()",
       "                turn_mark(\"gen_flushed\")"))
# first token, both paths
sub(ln("                if line.startswith(\"T \"):",
       "                    if cancel.is_set():",
       "                        return"),
    ln("                if line.startswith(\"T \"):",
       "                    if cancel.is_set():",
       "                        return",
       "                    if TURN_TRACE and \"gen_start\" in TURN and \"first_t\" not in TURN:",
       "                        turn_mark(\"first_t\")",
       "                        turn_print(len(ids))"), count=2)

sub(ln("        marked, marked_tools, changed = mark_literals(messages, tools, self.literals)",
       "        prompt = self.template.render(marked, tools=marked_tools, **kwargs)"),
    ln("        turn_mark(\"render_start\")",
       "        marked, marked_tools, changed = mark_literals(messages, tools, self.literals)",
       "        turn_mark(\"marked\")",
       "        prompt = self.template.render(marked, tools=marked_tools, **kwargs)",
       "        turn_mark(\"rendered\")"))

sub(ln("        def do_POST(self):",
       "            if not self._authorized() or self._foreign_page():"),
    ln("        def do_POST(self):",
       "            TURN.clear() if TURN_TRACE else None",
       "            turn_mark(\"http\")",
       "            if not self._authorized() or self._foreign_page():"))

sub(ln("                req = json.loads(self._body() or b\"{}\")"),
    ln("                raw_ = self._body()",
       "                turn_mark(\"body\")",
       "                req = json.loads(raw_ or b\"{}\")",
       "                turn_mark(\"json\")"))

sub(ln("            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_new, guard=svc._loop_guard_on(req))"),
    ln("            turn_mark(\"prepare_start\")",
       "            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_new, guard=svc._loop_guard_on(req))",
       "            turn_mark(\"prepared\")"), count=2)

out = s.encode("utf-8")
p.write_bytes(out)
print("patched", p, hashlib.sha256(out).hexdigest())
