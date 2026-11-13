"""A RAM slot carries a copy of the longest checkpoint its conversation starts with, and gives it back on take-back.
Switching to another conversation drops the model's checkpoints, so without it an edit of the last message after the
return reads the whole conversation again. Opt-in: STRATA_GLM_SLOT_CARRY_CKPT=1. RAM slots only."""
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


sub("""        uint64_t img = kNoImages;               // img_hash() of the pictures in `tokens`
    };
    std::vector<Slot> slots;
""", """        uint64_t img = kNoImages;               // img_hash() of the pictures in `tokens`
        // (STRATA_GLM_SLOT_CARRY_CKPT) a copy of the longest checkpoint `tokens` start with, per half: switching to
        // another conversation drops the model's checkpoints, and this brings the one an edited last turn needs back
        std::vector<int32_t> ck_tokens;
        std::vector<std::vector<float>> ck_bufs;
        int64_t ck_pos = -1;
    };
    std::vector<Slot> slots;
""")

sub("""    // A route that found a non-finite score (or an expert id out of range) means a NaN or an infinity in the state the
""", """    static const bool slot_carry_on = [] {
        const char* v = getenv("STRATA_GLM_SLOT_CARRY_CKPT");
        return v != nullptr && atoi(v) != 0;
    }();
    // the RAM slot holding the model's snapshot gets a copy of the longest checkpoint the snapshot starts with
    const auto slot_carry = [&]() {
        if (!slot_carry_on || !slot_ram || !snap_in_slot || ckpt_max <= 0) return;
        Slot* sl = nullptr;
        for (auto& x : slots)
            if (x.data && x.tokens == snap_tokens) sl = &x;
        if (sl == nullptr || sl->ck_pos >= 0) return;
        int best = -1;
        for (int c = 0; c < (int) ckpts.size(); ++c) {
            const auto& t = ckpts[(size_t) c].tokens;
            if (!t.empty() && t.size() < snap_tokens.size() &&
                (best < 0 || t.size() > ckpts[(size_t) best].tokens.size()) &&
                std::equal(t.begin(), t.end(), snap_tokens.begin()))
                best = c;
        }
        if (best < 0) return;
        model.ckpt_join();
        std::vector<std::vector<float>> bufs;
        int64_t pos = -1;
        for (auto* m = &model; m != nullptr; m = m->split_next_.get()) {
            if ((int) m->ckpt_pos_.size() <= best || m->ckpt_pos_[(size_t) best] < 0) return;
            if (pos >= 0 && m->ckpt_pos_[(size_t) best] != pos) return;
            pos = m->ckpt_pos_[(size_t) best];
            bufs.push_back(m->ckpt_buf_[(size_t) best]);
        }
        if (pos != (int64_t) ckpts[(size_t) best].tokens.size()) return;
        uint64_t bytes = 0;
        for (const auto& b : bufs) bytes += b.size() * sizeof(float);
        sl->ck_tokens = ckpts[(size_t) best].tokens;
        sl->ck_bufs = std::move(bufs);
        sl->ck_pos = pos;
        sl->bytes += bytes;   // (the RAM cap counts it from the next slot_put on)
    };
    // after a take-back (and ckpt_drop_past): the slot's carried checkpoint into a free or the least recently used one
    const auto slot_give = [&]() {
        if (!slot_carry_on || ckpt_max <= 0) return;
        const Slot* sl = nullptr;
        for (const auto& x : slots)
            if (x.data && x.ck_pos >= 0 && x.tokens == snap_tokens) sl = &x;
        if (sl == nullptr) return;
        for (const auto& c : ckpts)
            if (c.tokens == sl->ck_tokens) return;
        size_t halves = 0;
        for (auto* m = &model; m != nullptr; m = m->split_next_.get()) ++halves;
        if (halves != sl->ck_bufs.size()) return;
        if ((int) ckpts.size() < ckpt_max) ckpts.emplace_back();
        size_t c = 0;
        for (size_t i = 0; i < ckpts.size(); ++i) {
            if (ckpts[i].tokens.empty()) { c = i; break; }
            if (ckpts[i].used < ckpts[c].used) c = i;
        }
        model.ckpt_join();
        size_t h = 0;
        for (auto* m = &model; m != nullptr; m = m->split_next_.get(), ++h) {
            if (m->ckpt_buf_.size() <= c) {
                m->ckpt_buf_.resize(c + 1);
                m->ckpt_pos_.resize(c + 1, -1);
            }
            m->ckpt_buf_[c] = sl->ck_bufs[h];
            m->ckpt_pos_[c] = sl->ck_pos;
        }
        ckpts[c].tokens = sl->ck_tokens;
        ckpts[c].used = ++ckpt_clock;
        std::fprintf(stderr, "glm slots: gave back a checkpoint at %lld with the conversation\\n", (long long) sl->ck_pos);
    };
    // A route that found a non-finite score (or an expert id out of range) means a NaN or an infinity in the state the
""")

sub("""            slot_put("");              // the conversation in the model goes on differently past the checkpoint: kept
""", """            slot_put("");              // the conversation in the model goes on differently past the checkpoint: kept
            slot_carry();
""")

sub("""            slot_put("");              // the conversation in the model, before this prompt overwrites it
            reuse = slot_take(prompt);
            if (reuse > 0) ckpt_drop_past(0);   // another conversation's state now
""", """            slot_put("");              // the conversation in the model, before this prompt overwrites it
            slot_carry();
            reuse = slot_take(prompt);
            if (reuse > 0) {   // another conversation's state now
                ckpt_drop_past(0);
                slot_give();
            }
""")

p.write_bytes(s.encode('utf-8'))
print('patched', p, 'crlf' if crlf else 'lf')
