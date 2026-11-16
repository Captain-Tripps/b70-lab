"""Patch glm_mtp.dp.cpp: STRATA_GLM_MTP_DRAFT_IDS=<file> - the MTP draft vocabulary from a list of token ids.

The file is int32 little-endian token ids (dvocab.py: the most frequent tokens of a corpus).  The draft vocabulary is
those ids plus the digit-only and control / user-defined tokens (as the auto vocabulary keeps them); its longest id
prefix stays the in-place leading block and every other id is a gathered row.  Unset: unchanged.  Also: the gathered
rows are copied with one wait at the end instead of one a row (tens of thousands of rows now).
Usage: python patch_dvocab.py <tree root>
"""
import pathlib, sys

p = pathlib.Path(sys.argv[1]) / 'src' / 'core' / 'glm_mtp.dp.cpp'
s = p.read_text(encoding='utf-8')
assert 'STRATA_GLM_MTP_DRAFT_IDS' not in s, 'already patched'


def sub(old, new):
    global s
    assert s.count(old) == 1, ('not found once', old[:80])
    s = s.replace(old, new)


# 1. the id-list vocabulary, right after the digit / ascii scan
sub('''    int64_t lead = 0;
    if (env > 0) {''', '''    // SYCL port: STRATA_GLM_MTP_DRAFT_IDS=<file> (int32 ids, most frequent first or sorted) - the listed ids, the
    // digit-only and the control / user-defined tokens; the longest id prefix in place, the rest gathered
    static const std::string ids_path = [] {
        const char* e = getenv("STRATA_GLM_MTP_DRAFT_IDS");
        if (e == nullptr) e = getenv("MAYA_GLM_MTP_DRAFT_IDS");
        return std::string(e != nullptr ? e : "");
    }();
    if (!ids_path.empty()) {
        std::vector<uint8_t> in((size_t) N, 0);
        size_t listed = 0;
        if (FILE* f = std::fopen(ids_path.c_str(), "rb")) {
            int32_t id = 0;
            while (std::fread(&id, sizeof(id), 1, f) == 1)
                if (id >= 0 && id < N) { in[(size_t) id] = 1; ++listed; }
            std::fclose(f);
        }
        if (listed == 0) {
            std::fprintf(stderr, "glm mtp: STRATA_GLM_MTP_DRAFT_IDS=%s has no token ids - the auto draft vocabulary\\n",
                         ids_path.c_str());
        } else {
            for (int64_t i = 0; i < N; ++i) {
                const int ty = types != nullptr ? (int) types->items[(size_t) i].u : 1;
                if (dig[(size_t) i] || ty == 3 || ty == 4) in[(size_t) i] = 1;
            }
            int64_t lead_i = 0;
            while (lead_i < N && in[(size_t) lead_i]) ++lead_i;
            if (lead_i == 0) { in[0] = 1; lead_i = 1; while (lead_i < N && in[(size_t) lead_i]) ++lead_i; }
            std::vector<int32_t> extra_i;
            for (int64_t i = lead_i; i < N; ++i)
                if (in[(size_t) i]) extra_i.push_back((int32_t) i);
            mtp_vlead_ = (int) lead_i;
            mtp_vextra_ = std::move(extra_i);
            mtp_vin_ = std::move(in);
            std::fprintf(stderr, "glm mtp: the draft vocabulary from %s (%zu ids listed): %lld in place + %zu gathered\\n",
                         ids_path.c_str(), listed, (long long) lead_i, mtp_vextra_.size());
            return;
        }
    }
    int64_t lead = 0;
    if (env > 0) {''')

# 2. one wait for all the gathered row copies (in-order queue)
sub('''            for (int i = 0; i < dx && ok; ++i)
                ok = DPCT_CHECK_ERROR(dpct::get_in_order_queue().memcpy(
                         (uint8_t *)F->mtp_dx_w + (size_t)i * hb,
                         (const uint8_t *)head +
                             (size_t)mtp_vextra_[(size_t)i] * hb,
                         hb).wait()) == 0;''', '''            for (int i = 0; i < dx && ok; ++i)
                ok = DPCT_CHECK_ERROR(dpct::get_in_order_queue().memcpy(
                         (uint8_t *)F->mtp_dx_w + (size_t)i * hb,
                         (const uint8_t *)head +
                             (size_t)mtp_vextra_[(size_t)i] * hb,
                         hb)) == 0;
            ok = ok && DPCT_CHECK_ERROR(dpct::get_in_order_queue().wait()) == 0;''')

if '#include <cstdio>' not in s:
    s = '#include <cstdio>\n' + s
p.write_text(s, encoding='utf-8', newline='')
print('patched', p)
