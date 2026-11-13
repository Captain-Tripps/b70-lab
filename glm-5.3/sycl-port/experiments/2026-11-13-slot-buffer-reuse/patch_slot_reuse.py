"""A RAM slot save reuses the largest slot buffer dropped since the last save instead of a fresh one: a fresh buffer
is zero-filled by resize() and faulted in page by page, ~1.7 GB for a 115k conversation, on the request's critical
path. Up to N dropped buffers are kept (STRATA_GLM_SLOT_REUSE=N); only one from a conversation 1-1.25x this one's
length is reused, and dropped buffers not kept are freed on a side thread. STRATA_GLM_SLOT_TIMING=1 also logs the whole put: drops, the save call,
evictions. RAM slots only."""
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


sub("""    const auto slot_drop = [&](size_t i) {
        if (slots[i].data)                       // a RAM slot: its buffer simply dies
            slots[i].data.reset();
""", """    // (STRATA_GLM_SLOT_REUSE=N) up to N RAM slot buffers dropped since, the largest kept, for later saves; outside
    // the slot RAM cap (up to N x ~1.9 GB at 115k)
    static const size_t slot_reuse_n = [] {
        const char* v = getenv("STRATA_GLM_SLOT_REUSE");
        return v == nullptr ? (size_t) 0 : (size_t) std::max(0, std::min(8, atoi(v)));
    }();
    static const bool slot_reuse_on = slot_reuse_n > 0;
    static const bool slot_timing_on = getenv("STRATA_GLM_SLOT_TIMING") != nullptr;
    struct Spare {
        std::shared_ptr<std::vector<uint8_t>> buf;
        size_t n = 0;   // the positions of the conversation it held: a save of up to that many fits it
    };
    std::vector<Spare> slot_spares;
    const auto slot_drop = [&](size_t i) {
        if (!slot_reuse_on && slots[i].data)     // a RAM slot: its buffer simply dies
            slots[i].data.reset();
        else if (slots[i].data) {                // ... or waits for a later save; freeing ~1.7 GB takes ~0.1 s,
            auto d = std::move(slots[i].data);   // so the rest die on a side thread
            if (d.use_count() == 1) {
                slot_spares.push_back({std::move(d), slots[i].tokens.size()});
                if (slot_spares.size() > slot_reuse_n) {
                    size_t small = 0;
                    for (size_t k = 1; k < slot_spares.size(); ++k)
                        if (slot_spares[k].buf->capacity() < slot_spares[small].buf->capacity()) small = k;
                    d = std::move(slot_spares[small].buf);
                    slot_spares.erase(slot_spares.begin() + (long) small);
                }
            }
            if (d) std::thread([b = std::move(d)]() mutable { b.reset(); }).detach();
        }
""")

sub("""        if (slot_max <= 0 || snap_in_slot || snap_tokens.size() < slot_min) return;
""", """        if (slot_max <= 0 || snap_in_slot || snap_tokens.size() < slot_min) return;
        const auto t_put = std::chrono::steady_clock::now();
""")

sub("""            const auto t0 = std::chrono::steady_clock::now();
            std::string e;
            auto buf = std::make_shared<std::vector<uint8_t>>();
            buf->reserve(1 << 20);
            const uint64_t bytes = model.slot_save(*buf, e);
            if (bytes == 0) {
""", """            const auto t0 = std::chrono::steady_clock::now();
            std::string e;
            std::shared_ptr<std::vector<uint8_t>> buf;
            // a buffer too small grows by reallocating and copying, one far too big holds RAM the cap counts
            const size_t n_now = snap_tokens.size();
            size_t pick = SIZE_MAX;   // the tightest spare that fits
            for (size_t k = 0; k < slot_spares.size(); ++k)
                if (slot_spares[k].n >= n_now && slot_spares[k].n <= n_now + n_now / 4 &&
                    (pick == SIZE_MAX || slot_spares[k].n < slot_spares[pick].n))
                    pick = k;
            const bool reused = pick != SIZE_MAX;
            if (reused) {
                buf = std::move(slot_spares[pick].buf);
                slot_spares.erase(slot_spares.begin() + (long) pick);
            } else {
                buf = std::make_shared<std::vector<uint8_t>>();
                buf->reserve(1 << 20);
            }
            const uint64_t bytes = model.slot_save(*buf, e);
            const auto t_saved = std::chrono::steady_clock::now();
            if (bytes > 0 && buf->size() > bytes) buf->resize((size_t) bytes);   // (its capacity stays: counted below)
            if (bytes == 0) {
""")

sub("""            slots.push_back({snap_tokens, "", bytes, ++slot_clock});
            slots.back().data = buf;
            slots.back().img = snap_img_hash;
            snap_in_slot = true;
            uint64_t total = 0;
            for (const auto& s : slots) total += s.bytes;
            size_t evicted = 0;
            while (slots.size() > 1 && total > slot_cap) {
                const size_t i = slot_lru(slots.size() - 1);
                total -= slots[i].bytes;
                slot_drop(i);
                ++evicted;
            }
""", """            slots.push_back({snap_tokens, "", std::max<uint64_t>(bytes, buf->capacity()), ++slot_clock});
            slots.back().data = buf;
            slots.back().img = snap_img_hash;
            snap_in_slot = true;
            uint64_t total = 0;
            for (const auto& s : slots) total += s.bytes;
            size_t evicted = 0;
            while (slots.size() > 1 && total > slot_cap) {
                const size_t i = slot_lru(slots.size() - 1);
                total -= slots[i].bytes;
                slot_drop(i);
                ++evicted;
            }
            if (slot_timing_on) {
                const auto ms = [](std::chrono::steady_clock::time_point a, std::chrono::steady_clock::time_point b) {
                    return std::chrono::duration<double, std::milli>(b - a).count();
                };
                const auto t_end = std::chrono::steady_clock::now();
                std::fprintf(stderr, "glm slots: put %.0f ms - drops %.0f, save %.0f (%s buffer), after %.0f\\n",
                             ms(t_put, t_end), ms(t_put, t0), ms(t0, t_saved), reused ? "reused" : "new",
                             ms(t_saved, t_end));
            }
""")

p.write_bytes(s.encode('utf-8'))
print('patched', p, 'crlf' if crlf else 'lf')
