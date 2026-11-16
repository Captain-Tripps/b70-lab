"""Add an IQ2_S format to llama.cpp#31428's ESIMD grouped GEMM (fused-gemm-esimd.cpp / .hpp in <tree>/src/forkxmx).

usage: python patch_iq2s.py <forkxmx dir> <PR head ggml-sycl dir> <iq2s_code_table.inc>

IQ2_S, per 32 values (k step j of a 256-value block): 4 grid indices (qs byte | 2 high bits from qh[j]) into the
1024-entry iq2s_grid of 8 values, 4 sign bytes (qs[32 + 4j ..]) and one scale byte (scales[j]: low nibble for values
0-15, high nibble for 16-31). Every grid value is 8, 25 or 43, so the grid is kept in SLM as 2-bit levels (2 KB, the
size of the iq3_s table) and expanded in registers. A is rounded as the joint_matrix stage does:
f16(f32(d) * (0.5 + scale) * 0.25 * +-grid). The weight is taken in the canonical (AoS) layout only: the engine never
reorders it."""
import pathlib, sys

fx, prdir, table = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])

# header: the format list (a local copy beside the .cpp files, found before the PR head's)
h = (prdir / 'fused-gemm-esimd.hpp').read_text(encoding='utf-8')
old = 'std::is_same_v<block_q_t, block_iq3_xxs> ||'
assert h.count(old) == 1
h = h.replace(old, old + '\n                                                  std::is_same_v<block_q_t, block_iq2_s> ||')
(fx / 'fused-gemm-esimd.hpp').write_text(h, encoding='utf-8', newline='\n')

c = (fx / 'fused-gemm-esimd.cpp').read_text(encoding='utf-8')
if 'iq2s_grid_code2' in c:
    sys.exit('already patched')

helper = r'''
// grid_signed with a scale per 16-value half (iq2_s: scale nibble j of its scale byte covers values
// 16 j .. 16 j + 15 of the k step)
ESIMD_INLINE a_halves grid_signed2(simd<uint32_t, GROUPED_GEMM_RC * 8> ge,
                                   simd<uint32_t, GROUPED_GEMM_RC>     signs,
                                   simd<float, GROUPED_GEMM_RC>        d0,
                                   simd<float, GROUPED_GEMM_RC>        d1) {
    auto                                 gm = ge.template bit_cast_view<uint32_t, GROUPED_GEMM_RC, 8>();
    simd<uint32_t, GROUPED_GEMM_RC * 16> sg = signs.template replicate_vs_w_hs<GROUPED_GEMM_RC, 1, 16, 0>(0);
    simd<uint32_t, GROUPED_GEMM_RC * 16> k(0, 1);
    k &= 15;
    a_halves v;
#pragma unroll
    for (int h = 0; h < 2; ++h) {
        simd<uint32_t, GROUPED_GEMM_RC * 4> eh = gm.template select<GROUPED_GEMM_RC, 1, 4, 1>(0, 4 * h);
        simd<float, GROUPED_GEMM_RC * 16>   f  = eh.template bit_cast_view<uint8_t>();
        f.merge(-f, ((sg >> (k + 16 * h)) & 1) != 0);
        v.template select<GROUPED_GEMM_RC * 16, 1>(h * GROUPED_GEMM_RC * 16) = scale_half(f, h == 0 ? d0 : d1);
    }
    return v;
}

// four 2-bit levels (x, 8 bits) to the dword of their grid bytes: field i to byte i, level l to 8 + 17 l + (l >> 1)
// (0, 1, 2 -> 8, 25, 43)
ESIMD_INLINE simd<uint32_t, GROUPED_GEMM_RC * 4> iq2s_levels_to_bytes(simd<uint32_t, GROUPED_GEMM_RC * 4> x) {
    simd<uint32_t, GROUPED_GEMM_RC * 4> t = (x | (x << 6) | (x << 12) | (x << 18)) & 0x03030303u;
    return t * 17u + 0x08080808u + ((t >> 1) & 0x01010101u);
}
}  // namespace grouped_gemm_esimd
'''
anchor = '}  // namespace grouped_gemm_esimd\n'
assert c.count(anchor) == 1
c = c.replace(anchor, helper, 1)

loader = table.read_text(encoding='utf-8') + r'''
template <int MR> struct grouped_gemm_esimd_a<block_iq2_s, MR> {
    static constexpr bool supported = true;
    static constexpr int  qk        = QK_K;
    static constexpr bool whole     = false;
    // the 1024 grid entries as 2-bit levels, two a dword: 2 KB of SLM (the 8-byte entries would take 8 KB a thread)
    static constexpr int  slm_bytes = 512 * sizeof(uint32_t);
    static ESIMD_INLINE void init_slm() {
        using namespace grouped_gemm_esimd;
#pragma unroll
        for (int i = 0; i < 512; i += 64) {
            slm_block_store<uint32_t, 64>(i * 4, block_load<uint32_t, 64>(iq2s_grid_code2 + i));
        }
    }
    struct raw {
        grouped_gemm_esimd::simd<uint32_t, MR> q;      // the k step's 4 grid index bytes
        grouped_gemm_esimd::simd<uint32_t, MR> qh;     // its qh byte
        grouped_gemm_esimd::simd<uint32_t, MR> signs;  // its 32 sign bits
        grouped_gemm_esimd::simd<float, MR>    d0;     // the scale of values 0-15
        grouped_gemm_esimd::simd<float, MR>    d1;     // and of 16-31
    };
    struct sb_t {
        grouped_gemm_esimd::simd<float, MR>    d;
        grouped_gemm_esimd::simd<uint32_t, MR> sc0;  // scale bytes 0-3
        grouped_gemm_esimd::simd<uint32_t, MR> sc1;  // and 4-7
    };
    // AoS block: d at 0, qs at 2 (32 index bytes, then 32 sign bytes), qh at 66, scales at 74; 82 bytes. The
    // SoA offsets are placeholders: ok() takes the AoS layout only.
    static constexpr grouped_gemm_esimd::field QS = { 0, QK_K / 8, 2 }, SG = { QK_K / 8, QK_K / 8, 2 + QK_K / 8 },
                                               QH = { QK_K / 4, QK_K / 32, 2 + QK_K / 4 },
                                               SC = { QK_K / 4 + QK_K / 32, QK_K / 32, 2 + QK_K / 4 + QK_K / 32 },
                                               D  = { QK_K / 4 + QK_K / 16, 2, 0 };
    static bool ok(const int K, const bool aos) { return aos && K % qk == 0; }
    template <typename Sl> static ESIMD_INLINE void load_sb(sb_t & sb, const Sl & s, const int ib) {
        using namespace grouped_gemm_esimd;
        simd<uint16_t, MR> dh = s.u16(D, ib, 0);
        sb.d   = simd<sycl::half, MR>(dh.template bit_cast_view<sycl::half>());
        sb.sc0 = s.template rows<1>(SC, ib, 0);
        sb.sc1 = s.template rows<1>(SC, ib, 4);
    }
    template <typename Sl> static ESIMD_INLINE void load(raw & r, sb_t & sb, const Sl & s, const int kb, const int j) {
        using namespace grouped_gemm_esimd;
        const int ib = kb / 8;
        r.q     = s.template rows<1>(QS, ib, 4 * j);
        r.qh    = (s.template rows<1>(QH, ib, 4 * (j / 4)) >> (8 * (j % 4))) & 0xffu;
        r.signs = s.template rows<1>(SG, ib, 4 * j);
        const simd<uint32_t, MR> sc = ((j < 4 ? sb.sc0 : sb.sc1) >> (8 * (j % 4))) & 0xffu;
        r.d0 = sb.d * (0.5f + simd<float, MR>(sc & 0xfu)) * 0.25f;
        r.d1 = sb.d * (0.5f + simd<float, MR>(sc >> 4)) * 0.25f;
    }

    template <int g> static ESIMD_INLINE grouped_gemm_esimd::a_halves decode(raw & r) {
        using namespace grouped_gemm_esimd;
        // the row group's 4 grid indices a row, as [row][entry]
        simd<uint32_t, GROUPED_GEMM_RC * 4> qb =
            r.q.template select<GROUPED_GEMM_RC, 1>(g * GROUPED_GEMM_RC).template bit_cast_view<uint8_t>();
        simd<uint32_t, GROUPED_GEMM_RC>     qr = r.qh.template select<GROUPED_GEMM_RC, 1>(g * GROUPED_GEMM_RC);
        simd<uint32_t, GROUPED_GEMM_RC * 4> qh = qr.template replicate_vs_w_hs<GROUPED_GEMM_RC, 1, 4, 0>(0);
        simd<uint32_t, GROUPED_GEMM_RC * 4> e(0, 1);
        e &= 3;
        simd<uint32_t, GROUPED_GEMM_RC * 4> idx  = qb | (((qh >> (2 * e)) & 3u) << 8);
        simd<uint32_t, GROUPED_GEMM_RC * 4> code = slm_gather<uint32_t, GROUPED_GEMM_RC * 4>((idx >> 1) * 4);
        code = (code >> ((idx & 1u) * 16)) & 0xffffu;
        // dword 2 e + h of a row holds bytes 4 h .. 4 h + 3 of its entry e
        simd<uint32_t, GROUPED_GEMM_RC * 8> ge;
        ge.template select<GROUPED_GEMM_RC * 4, 2>(0) = iq2s_levels_to_bytes(code & 0xffu);
        ge.template select<GROUPED_GEMM_RC * 4, 2>(1) = iq2s_levels_to_bytes(code >> 8);
        return grid_signed2(ge, r.signs.template select<GROUPED_GEMM_RC, 1>(g * GROUPED_GEMM_RC),
                            r.d0.template select<GROUPED_GEMM_RC, 1>(g * GROUPED_GEMM_RC),
                            r.d1.template select<GROUPED_GEMM_RC, 1>(g * GROUPED_GEMM_RC));
    }
};

'''
anchor2 = '// T is the dpas operand type, sycl::half or bfloat16'
assert c.count(anchor2) == 1
c = c.replace(anchor2, loader + anchor2, 1)

inst = 'GROUPED_GEMM_ESIMD_INSTANCE(block_iq3_xxs)\n'
assert c.count(inst) == 1
c = c.replace(inst, inst + 'GROUPED_GEMM_ESIMD_INSTANCE(block_iq2_s)\n', 1)
(fx / 'fused-gemm-esimd.cpp').write_text(c, encoding='utf-8', newline='\n')
print('patched iq2_s into', fx)
