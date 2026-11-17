#define MAYA_FG_BN 64   // the tile width the ESIMD kernel was built and tuned with (GLM L14)
// strata_esimd_shim.cpp - the llama.cpp SYCL fork's ESIMD grouped dequant GEMM (fused-gemm-esimd.cpp, llama.cpp#31428
// plus the GLM lab's IQ2_S and 64-wide tiles) behind a plain C entry for Strata's grouped prefill experts
// (STRATA_NIGHT_PREFILL_ESIMD). Built apart from Strata's TUs with the fork's own headers: the fork's dpct helper and
// Strata's SYCLomatic dpct headers both define namespace dpct.
//
// Strata keeps every expert as one blob in a slot pool, the slots 256-byte aligned. The kernel reads tile t's weights
// at base + tile.expert * expert_stride, so expert_stride = 256 and tile.expert = (blob - base) / 256 with base the
// lowest blob of the call: no change to the kernel.
#include "common.hpp"
#include "fused-gemm-esimd.hpp"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <map>
#include <mutex>
#include <vector>

// settings the fork's headers name (ggml-sycl.cpp's defaults); only the ESIMD kernel is linked
int g_ggml_sycl_xmx_gather_types = GGML_SYCL_XMX_GATHER_TYPES_DEFAULT;
int g_ggml_sycl_xmx_gather_shapes = GGML_SYCL_XMX_GATHER_SHAPES_DEFAULT;
int g_ggml_sycl_dynamic_precision = GGML_SYCL_DYNAMIC_PRECISION_DEFAULT;
int g_ggml_sycl_mmid_sched = GGML_SYCL_MMID_SCHED_DEVICE;
int g_ggml_sycl_dynamic_required_precision = GGML_SYCL_DYNAMIC_PRECISION_F32;

int ggml_sycl_get_env(const char* name, int default_val) {
    const char* v = std::getenv(name);
    return v != nullptr && v[0] != '\0' ? std::atoi(v) : default_val;
}

namespace {

constexpr int BN = GGML_SYCL_FG_BN;   // 64: rows of one tile, the packed B columns of one work-group
constexpr size_t UNIT = 256;          // Strata's slot alignment

// per queue: grow-only device buffers (an in-order queue finishes the previous call before the next reuses them), and
// a ring of pinned host tile lists: each copy reads its own list, and a list is reused only once its copy is done
constexpr int RING = 16;
struct HostTiles {
    ggml_sycl_grouped_gemm_tile* p = nullptr;
    size_t cap = 0;
    sycl::event done;
};
struct Bufs {
    ggml_sycl_grouped_gemm_tile* tiles = nullptr;
    size_t tiles_cap = 0;
    sycl::half* packed = nullptr;
    size_t packed_cap = 0;
    std::vector<ggml_sycl_grouped_gemm_tile> host;
    HostTiles ring[RING];
    int next = 0;
};

Bufs& bufs_for(sycl::queue* q) {
    static std::mutex mu;
    static std::map<sycl::queue*, Bufs*> all;
    std::lock_guard<std::mutex> g(mu);
    Bufs*& b = all[q];
    if (b == nullptr) b = new Bufs();
    return *b;
}

template <typename T> T* grow(T* p, size_t& cap, size_t need, sycl::queue& q) {
    if (need <= cap) return p;
    if (p) { q.wait(); sycl::free(p, q); }
    cap = need + need / 4;
    return sycl::malloc_device<T>(cap, q);
}

template <typename F> bool visit_block(int type, F&& f) {
    switch (type) {
        case 18: f((block_iq3_xxs*) nullptr); return true;   // IQ3_XXS
        case 20: f((block_iq4_nl*) nullptr);  return true;   // IQ4_NL
        case 21: f((block_iq3_s*) nullptr);   return true;   // IQ3_S
        case 22: f((block_iq2_s*) nullptr);   return true;   // IQ2_S
        case 23: f((block_iq4_xs*) nullptr);  return true;   // IQ4_XS
        default: return false;                                // Q2_0 (42) and the rest: Strata's own path
    }
}

}  // namespace

// Y[r][m] = sum_k W_e[m][k] * X[r][k] for every entry i: rows r in [row0[i], row0[i] + rows[i]) of X (FP16, row stride K)
// and Y (FP32, row stride M), W_e the entry's weight rows at w[i] in ggml block layout (type = ggml type id).
// Returns 1 when launched on `queue`, 0 (nothing launched) when the type, shape or alignment is not covered.
extern "C" int strata_esimd_grouped(void* queue, int type, const void* const* w, const int64_t* row0, const int32_t* rows,
                                    int n_ent, const uint16_t* x, float* y, int M, int K) {
    sycl::queue* q = (sycl::queue*) queue;
    if (n_ent <= 0) return 1;
    if (!ggml_sycl_grouped_gemm_esimd_enabled() || K % 2 != 0) return 0;
    const char* base = (const char*) w[0];
    for (int i = 1; i < n_ent; ++i) base = std::min(base, (const char*) w[i]);
    Bufs& B = bufs_for(q);
    B.host.clear();
    for (int i = 0; i < n_ent; ++i) {
        const size_t d = (size_t) ((const char*) w[i] - base);
        if (d % UNIT != 0 || d / UNIT > (size_t) INT32_MAX) return 0;
        const int64_t end = row0[i] + rows[i];
        for (int64_t n0 = row0[i]; n0 < end; n0 += BN)
            B.host.push_back({ (int32_t) (d / UNIT), (int32_t) n0, (int32_t) std::min<int64_t>(n0 + BN, end) });
    }
    const int64_t n_tiles = (int64_t) B.host.size();
    if (n_tiles == 0) return 1;
    const int Npad = (int) (n_tiles * BN);
    const int kq = K / 2;
    B.tiles = grow(B.tiles, B.tiles_cap, (size_t) n_tiles, *q);
    B.packed = grow(B.packed, B.packed_cap, (size_t) K * Npad, *q);
    if (!B.tiles || !B.packed) return 0;
    {
        HostTiles& h = B.ring[B.next];
        B.next = (B.next + 1) % RING;
        h.done.wait();
        if (h.cap < (size_t) n_tiles) {
            if (h.p) sycl::free(h.p, *q);
            h.cap = (size_t) n_tiles + (size_t) n_tiles / 4;
            h.p = sycl::malloc_host<ggml_sycl_grouped_gemm_tile>(h.cap, *q);
            if (!h.p) { h.cap = 0; return 0; }
        }
        std::copy(B.host.begin(), B.host.end(), h.p);
        h.done = q->memcpy(B.tiles, h.p, (size_t) n_tiles * sizeof(ggml_sycl_grouped_gemm_tile));
    }
    // B: X's rows as [K/2][Npad][2] half, tile t's rows at columns t*BN.., zero past its n1
    {
        const ggml_sycl_grouped_gemm_tile* tiles = B.tiles;
        sycl::half* packed = B.packed;
        const sycl::half* xh = (const sycl::half*) x;
        q->parallel_for(sycl::range<1>((size_t) Npad * kq), [=](sycl::id<1> id) {
            const size_t idx = id[0];
            const int k2 = (int) (idx / Npad);
            const int n = (int) (idx - (size_t) k2 * Npad);
            const ggml_sycl_grouped_gemm_tile t = tiles[n / BN];
            const int row = t.n0 + n % BN;
            sycl::half v0 = 0.0f, v1 = 0.0f;
            if (row < t.n1) {
                const sycl::half* s = xh + (size_t) row * K + 2 * k2;
                v0 = s[0];
                v1 = s[1];
            }
            sycl::half* o = packed + ((size_t) k2 * Npad + n) * 2;
            o[0] = v0;
            o[1] = v1;
        });
    }
    bool ok = false;
    visit_block(type, [&](auto* tag) {
        using block_q_t = std::remove_pointer_t<decltype(tag)>;
        ok = ggml_sycl_grouped_gemm_esimd<block_q_t, sycl::half, 16>(base, UNIT, B.tiles, B.packed, y, M, Npad, K,
                                                                     ggml_sycl_grouped_gemm_rows{}, false, n_tiles, q);
    });
    return ok ? 1 : 0;   // a decline after the pack launched nothing that writes y
}

// h16[r][k] = silu(gu[r][k]) * gu[r][640 + k] for gate/up stacked as [gate 640 | up 640] (the ESIMD layout),
// the same math and rounding as Strata's swiglu_interleaved (FP32 silu with native exp, FP16 saturating store)
extern "C" void strata_swiglu_split(const float* gu, uint16_t* h16, int64_t n, void* queue) {
    if (n <= 0) return;
    sycl::queue* q = (sycl::queue*) queue;
    q->parallel_for(sycl::range<1>((size_t) n * 640), [=](sycl::id<1> id) {
        const int64_t i = (int64_t) id[0];
        const int64_t r = i / 640, k = i % 640;
        const float g = gu[r * 1280 + k], u = gu[r * 1280 + 640 + k];
        float v = g / (1.0f + sycl::native::exp(-g)) * u;
        v = sycl::fmin(sycl::fmax(v, -65504.0f), 65504.0f);
        h16[i] = sycl::bit_cast<uint16_t>(sycl::half(v));
    });
}
