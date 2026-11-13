"""On top of the slot checkpoint carry: a prompt no slot is a prefix of (an edited last message straight after a
switch) takes back the slot whose carried checkpoint it starts with, restores that checkpoint and reads only the
rest. Without it, it reads the whole conversation. Opt-in: STRATA_GLM_SLOT_CKPT_RESUME=1 with
STRATA_GLM_SLOT_CARRY_CKPT=1. RAM slots, text prompts only."""
import sys
from pathlib import Path

p = Path(sys.argv[1]) / 'src' / 'program' / 'generate.cpp'
s = p.read_bytes().decode('utf-8')
crlf = '\r\n' in s


def sub(old, new):
    global s
    if crlf:
        old = old.replace('\n', '\r\n'); new = new.replace('\n', '\r\n')
    n = s.count(old)
    if n != 1:
        sys.exit(f'anchor matched {n} times: {old[:70]!r}')
    s = s.replace(old, new)


sub("""    // A route that found a non-finite score (or an expert id out of range) means a NaN or an infinity in the state the
""", """    static const bool slot_resume_on = [] {
        const char* v = getenv("STRATA_GLM_SLOT_CKPT_RESUME");
        return slot_carry_on && v != nullptr && atoi(v) != 0;
    }();
    // the longest carried checkpoint this prompt starts with, past every slot it continues whole (SIZE_MAX: none)
    const auto slot_ck_pick = [&](const std::vector<int32_t>& prompt) -> size_t {
        if (!slot_resume_on || ckpt_max <= 0 || !cur_img_pos.empty()) return SIZE_MAX;
        size_t whole = 0;
        for (const auto& sl : slots)
            if (sl.tokens.size() > whole && sl.tokens.size() < prompt.size() &&
                std::equal(sl.tokens.begin(), sl.tokens.end(), prompt.begin()))
                whole = sl.tokens.size();
        size_t best = SIZE_MAX, len = whole;
        for (size_t i = 0; i < slots.size(); ++i) {
            const auto& t = slots[i].ck_tokens;
            if (slots[i].data && slots[i].ck_pos >= 0 && slots[i].img == kNoImages && t.size() > len &&
                t.size() < prompt.size() && std::equal(t.begin(), t.end(), prompt.begin())) {
                best = i;
                len = t.size();
            }
        }
        return best;
    };
    // that slot back in the model, then its checkpoint: the tokens the checkpoint covers (0: none, the model reset)
    const auto slot_take_ck = [&](const std::vector<int32_t>& prompt, size_t i) -> size_t {
        const auto t0 = std::chrono::steady_clock::now();
        std::string e;
        if (!model.slot_load(*slots[i].data, (int64_t) slots[i].tokens.size(), e)) {
            note("taking a conversation back for its checkpoint failed (" + e + ") - reading its prompt again");
            slot_drop(i);
            snap_tokens.clear();
            return 0;
        }
        snap_tokens = slots[i].tokens;
        snap_img_hash = slots[i].img;
        snap_in_slot = true;
        slots[i].used = ++slot_clock;
        slots[i].anchor = false;
        ckpt_drop_past(0);
        slot_give();
        int c = -1;
        for (int k = 0; k < (int) ckpts.size(); ++k)
            if (ckpts[(size_t) k].tokens == slots[i].ck_tokens) c = k;
        if (c < 0 || !model.ckpt_restore(c, e)) {
            note("a carried checkpoint did not come back (" + e + ") - reading the prompt again");
            snap_tokens.clear();
            ckpt_drop_past(0);
            return 0;
        }
        ckpts[(size_t) c].used = ++ckpt_clock;
        snap_tokens.clear();   // the snapshot's position lies past the checkpoint: overwritten from here on
        const size_t len = ckpts[(size_t) c].tokens.size();
        char m[200];
        std::snprintf(m, sizeof m, "took back a %zu-token conversation from RAM for its checkpoint at %zu (%.1f s); %zu "
                      "new tokens to read", slots[i].tokens.size(), len,
                      std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count(), prompt.size() - len);
        note(m);
        return len;
    };
    // A route that found a non-finite score (or an expert id out of range) means a NaN or an infinity in the state the
""")

sub("""            slot_carry();
            reuse = slot_take(prompt);
            if (reuse > 0) {   // another conversation's state now
                ckpt_drop_past(0);
                slot_give();
            }
""", """            slot_carry();
            const size_t ck_slot = slot_ck_pick(prompt);
            if (ck_slot != SIZE_MAX) {
                reuse = slot_take_ck(prompt, ck_slot);
                from_ckpt = reuse > 0;
            } else {
                reuse = slot_take(prompt);
                if (reuse > 0) {   // another conversation's state now
                    ckpt_drop_past(0);
                    slot_give();
                }
            }
""")

p.write_bytes(s.encode('utf-8'))
print('patched', p, 'crlf' if crlf else 'lf')
