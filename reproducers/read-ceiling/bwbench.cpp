// bwbench.cpp - single-kernel DRAM read-bandwidth sweep for an Intel Arc GPU.
//
// Build with all four kernels (sub-group block load enabled):
//   icpx -fsycl -O3 -std=c++20 -DBW_SG bwbench.cpp -o bwbench.exe
// Build with the three portable kernels only:
//   icpx -fsycl -O3 -std=c++20 bwbench.cpp -o bwbench.exe
// Usage:
//   bwbench [gpu_index=0] [reps=50]
#include <sycl/sycl.hpp>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using u32 = uint32_t;
using v4 = sycl::vec<u32, 4>;

static constexpr size_t MB = 1024ull * 1024ull;
static constexpr size_t POOL_BYTES = 256ull * MB;  // >= 4x an assumed 32 MB L2
static constexpr size_t OUT_SLOTS = 1u << 20;

/* ---------------------------------------------------------------- kernels */

struct Fill {
  u32* p;
  void operator()(sycl::id<1> i) const { p[i] = static_cast<u32>(i[0]); }
};

struct FillRand {   // (incompressible: Xe2 memory compression makes p[i]=i read faster than DRAM)
  u32* p;
  u32 seed;
  void operator()(sycl::id<1> i) const {
    u32 x = static_cast<u32>(i[0]) * 2654435761u ^ seed;
    x ^= x >> 16; x *= 0x7feb352du; x ^= x >> 15; x *= 0x846ca68bu; x ^= x >> 16;
    p[i] = x;
  }
};

struct ReadX4 {
  const v4* in;
  u32* out;
  size_t n;
  void operator()(sycl::nd_item<1> it) const {
    const size_t stride = it.get_global_range(0);
    u32 acc = 0;
    for (size_t i = it.get_global_id(0); i < n; i += stride) {
      const v4 v = in[i];
      acc ^= v.x() ^ v.y() ^ v.z() ^ v.w();
    }
    acc = sycl::reduce_over_group(it.get_group(), acc, sycl::bit_xor<>());
    if (it.get_local_id(0) == 0) out[it.get_group(0)] = acc;
  }
};

struct ReadX8 {
  const v4* in;
  u32* out;
  size_t half;
  void operator()(sycl::nd_item<1> it) const {
    const size_t stride = it.get_global_range(0);
    u32 acc = 0;
    for (size_t i = it.get_global_id(0); i < half; i += stride) {
      const v4 a = in[i];
      const v4 b = in[i + half];
      acc ^= a.x() ^ a.y() ^ a.z() ^ a.w() ^ b.x() ^ b.y() ^ b.z() ^ b.w();
    }
    acc = sycl::reduce_over_group(it.get_group(), acc, sycl::bit_xor<>());
    if (it.get_local_id(0) == 0) out[it.get_group(0)] = acc;
  }
};

struct CopyX4 {
  const v4* in;
  v4* dst;
  u32* out;
  size_t n;
  void operator()(sycl::nd_item<1> it) const {
    const size_t stride = it.get_global_range(0);
    u32 acc = 0;
    for (size_t i = it.get_global_id(0); i < n; i += stride) {
      const v4 v = in[i];
      dst[i] = v;
      acc ^= v.x() ^ v.y() ^ v.z() ^ v.w();
    }
    acc = sycl::reduce_over_group(it.get_group(), acc, sycl::bit_xor<>());
    if (it.get_local_id(0) == 0) out[it.get_group(0)] = acc;
  }
};

#ifdef BW_SG
// One 256 B block (64 u32) per sub-group per iteration, lane l takes elements
// blk*64 + l, +l+16, +l+32, +l+48 via the oneAPI sub-group block load.
struct ReadSG {
  u32* in;
  u32* out;
  size_t nblocks;
  [[sycl::reqd_sub_group_size(16)]]
  void operator()(sycl::nd_item<1> it) const {
    const sycl::sub_group sg = it.get_sub_group();
    const size_t sgs = sg.get_local_range().size();
    const size_t nsub = it.get_global_range(0) / sgs;
    u32 acc = 0;
    for (size_t blk = it.get_global_id(0) / sgs; blk < nblocks; blk += nsub) {
      sycl::multi_ptr<u32, sycl::access::address_space::global_space> mp(in + blk * 64);
      const v4 v = sg.load<4>(mp);
      acc ^= v.x() ^ v.y() ^ v.z() ^ v.w();
    }
    acc = sycl::reduce_over_group(it.get_group(), acc, sycl::bit_xor<>());
    if (it.get_local_id(0) == 0) out[it.get_group(0)] = acc;
  }
};
#endif

/* ---------------------------------------------------------------- harness */

static double median(std::vector<double> v) {
  if (v.empty()) return 0.0;
  std::sort(v.begin(), v.end());
  const size_t n = v.size();
  return (n & 1) ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

struct Row {
  double dev_us, dev_gbps, b2b_us, b2b_gbps;
};

template <class Make>
static Row run_one(sycl::queue& q, const char* name, size_t bytes, size_t traffic,
                   size_t wg, size_t groups, const std::vector<void*>& src,
                   const std::vector<void*>& dst, u32* out, Make make, int reps) {
  const size_t nsrc = src.size();
  const size_t ndst = dst.empty() ? 1 : dst.size();
  auto submit = [&](int i) {
    void* s = src[static_cast<size_t>(i) % nsrc];
    void* d = dst.empty() ? nullptr : dst[static_cast<size_t>(i) % ndst];
    return q.submit([&](sycl::handler& h) {
      h.parallel_for(sycl::nd_range<1>(groups * wg, wg), make(s, d));
    });
  };

  for (int i = 0; i < 5; ++i) submit(i);
  q.wait();

  std::vector<sycl::event> evs;
  evs.reserve(static_cast<size_t>(reps));
  for (int i = 0; i < reps; ++i) evs.push_back(submit(i));
  q.wait();

  double med_us = -1.0;
  try {
    std::vector<double> dev;
    dev.reserve(evs.size());
    for (auto& e : evs) {
      const double t0 =
          static_cast<double>(e.get_profiling_info<sycl::info::event_profiling::command_start>());
      const double t1 =
          static_cast<double>(e.get_profiling_info<sycl::info::event_profiling::command_end>());
      dev.push_back((t1 - t0) / 1000.0);
    }
    med_us = median(dev);
  } catch (const std::exception& e) {
    std::fprintf(stderr, "profiling unavailable (%s), using wall clock\n", e.what());
  }

  const auto w0 = std::chrono::steady_clock::now();
  for (int i = 0; i < reps; ++i) submit(i);
  q.wait();
  const auto w1 = std::chrono::steady_clock::now();
  const double b2b_us =
      std::chrono::duration<double, std::micro>(w1 - w0).count() / static_cast<double>(reps);
  if (med_us < 0.0) med_us = b2b_us;

  const Row r{med_us, static_cast<double>(traffic) / (med_us * 1e-6) / 1e9, b2b_us,
              static_cast<double>(traffic) / (b2b_us * 1e-6) / 1e9};
  std::printf("%s,%zu,%zu,%zu,%.2f,%.1f,%.2f,%.1f\n", name, bytes, wg, groups, r.dev_us,
              r.dev_gbps, r.b2b_us, r.b2b_gbps);
  std::fflush(stdout);
  return r;
}

/* ----------------------------------------------------------- verification */

// in[k] = k, so the XOR of the four components of vec element i is:
static u32 vec_xor_pat(size_t i) {
  const u32 b = static_cast<u32>(4 * i);
  return b ^ (b + 1) ^ (b + 2) ^ (b + 3);
}

static int check(const char* what, const std::vector<u32>& got, const std::vector<u32>& exp) {
  for (size_t i = 0; i < exp.size(); ++i) {
    if (got[i] != exp[i]) {
      std::fprintf(stderr, "check FAILED: %s (group %zu: got %u want %u)\n", what, i, got[i],
                   exp[i]);
      return 1;
    }
  }
  std::fprintf(stderr, "check ok: %s\n", what);
  return 0;
}

static int verify(sycl::queue& q, u32* out) {
  const size_t nvec = 4096, wg = 256, groups = 4;
  const size_t bytes = nvec * 16;
  const size_t stride = groups * wg;
  void* a = sycl::malloc_device(bytes, q);
  void* b = sycl::malloc_device(bytes, q);
  if (!a || !b) {
    std::fprintf(stderr, "verify: allocation failed\n");
    return 1;
  }
  q.submit([&](sycl::handler& h) {
     h.parallel_for(sycl::range<1>(nvec * 4), Fill{static_cast<u32*>(a)});
   }).wait();

  std::vector<u32> got(groups), exp(groups);
  int bad = 0;
  auto fetch = [&] { q.memcpy(got.data(), out, groups * sizeof(u32)).wait(); };

  // read_u32x4
  q.submit([&](sycl::handler& h) {
     h.parallel_for(sycl::nd_range<1>(groups * wg, wg),
                    ReadX4{static_cast<const v4*>(a), out, nvec});
   }).wait();
  fetch();
  for (size_t g = 0; g < groups; ++g) {
    u32 acc = 0;
    for (size_t l = 0; l < wg; ++l)
      for (size_t i = g * wg + l; i < nvec; i += stride) acc ^= vec_xor_pat(i);
    exp[g] = acc;
  }
  bad |= check("read_u32x4", got, exp);

  // read_u32x8
  const size_t half = nvec / 2;
  q.submit([&](sycl::handler& h) {
     h.parallel_for(sycl::nd_range<1>(groups * wg, wg),
                    ReadX8{static_cast<const v4*>(a), out, half});
   }).wait();
  fetch();
  for (size_t g = 0; g < groups; ++g) {
    u32 acc = 0;
    for (size_t l = 0; l < wg; ++l)
      for (size_t i = g * wg + l; i < half; i += stride)
        acc ^= vec_xor_pat(i) ^ vec_xor_pat(i + half);
    exp[g] = acc;
  }
  bad |= check("read_u32x8", got, exp);

  // copy_u32x4
  q.submit([&](sycl::handler& h) {
     h.parallel_for(sycl::nd_range<1>(groups * wg, wg),
                    CopyX4{static_cast<const v4*>(a), static_cast<v4*>(b), out, nvec});
   }).wait();
  fetch();
  for (size_t g = 0; g < groups; ++g) {
    u32 acc = 0;
    for (size_t l = 0; l < wg; ++l)
      for (size_t i = g * wg + l; i < nvec; i += stride) acc ^= vec_xor_pat(i);
    exp[g] = acc;
  }
  bad |= check("copy_u32x4", got, exp);
  std::vector<u32> hb(nvec * 4);
  q.memcpy(hb.data(), b, bytes).wait();
  int copied = 0;
  for (size_t k = 0; k < hb.size(); ++k)
    if (hb[k] != static_cast<u32>(k)) {
      copied = 1;
      break;
    }
  std::fprintf(stderr, "check %s: copy_u32x4 destination\n", copied ? "FAILED" : "ok");
  bad |= copied;

#ifdef BW_SG
  // read_subgroup_block
  const size_t nblocks = nvec * 4 / 64;
  const size_t nsub = groups * wg / 16;
  const size_t blocks_per_group = wg / 16;
  q.submit([&](sycl::handler& h) {
     h.parallel_for(sycl::nd_range<1>(groups * wg, wg),
                    ReadSG{static_cast<u32*>(a), out, nblocks});
   }).wait();
  fetch();
  for (size_t g = 0; g < groups; ++g) {
    u32 acc = 0;
    for (size_t s = 0; s < blocks_per_group; ++s)
      for (size_t blk = g * blocks_per_group + s; blk < nblocks; blk += nsub)
        for (size_t e = 0; e < 64; ++e) acc ^= static_cast<u32>(blk * 64 + e);
    exp[g] = acc;
  }
  bad |= check("read_subgroup_block", got, exp);
#endif

  sycl::free(a, q);
  sycl::free(b, q);
  return bad;
}

/* ------------------------------------------------------------------- main */

struct Best {
  double gbps = -1.0;
  size_t wg = 0;
  size_t groups = 0;
  std::string kernel;
};

int main(int argc, char** argv) {
  const size_t gpu_index =
      (argc > 1) ? static_cast<size_t>(std::atoi(argv[1])) : static_cast<size_t>(0);
  int reps = (argc > 2) ? std::atoi(argv[2]) : 50;
  if (reps < 1) reps = 1;

  std::vector<sycl::device> gpus;
  for (const auto& p : sycl::platform::get_platforms())
    for (const auto& d : p.get_devices())
      if (d.is_gpu()) gpus.push_back(d);
  if (gpus.empty()) {
    std::fprintf(stderr, "no SYCL GPU found\n");
    return 1;
  }
  if (gpu_index >= gpus.size()) {
    std::fprintf(stderr, "gpu_index %zu out of range (%zu GPU devices)\n", gpu_index,
                 gpus.size());
    return 1;
  }

  const sycl::device dev = gpus[gpu_index];
  if (!dev.has(sycl::aspect::usm_device_allocations)) {
    std::fprintf(stderr, "device does not support USM device allocations\n");
    return 1;
  }

  sycl::queue q(dev, sycl::property_list{sycl::property::queue::in_order{},
                                         sycl::property::queue::enable_profiling{}});

  const size_t cu = dev.get_info<sycl::info::device::max_compute_units>();
  const size_t gmem = dev.get_info<sycl::info::device::global_mem_size>();
  std::fprintf(stderr, "device[%zu]: %s\n", gpu_index,
               dev.get_info<sycl::info::device::name>().c_str());
  std::fprintf(stderr, "  CUs: %zu, global mem: %.1f GB, max work-group: %zu, reps: %d\n", cu,
               static_cast<double>(gmem) / 1e9,
               dev.get_info<sycl::info::device::max_work_group_size>(), reps);

  u32* out = sycl::malloc_device<u32>(OUT_SLOTS, q);
  if (!out) {
    std::fprintf(stderr, "output allocation failed\n");
    return 1;
  }
  const int bad = verify(q, out);
  std::fprintf(stderr, "verification: %s\n", bad ? "FAILED" : "all checks passed");

  std::printf("kernel,bytes,wg,groups,median_dev_us,dev_GBps,median_backtoback_us,b2b_GBps\n");

  const double sizes[] = {0.5, 1, 2, 4, 8, 12, 17, 24, 32, 64};
  for (double mbs : sizes) {
    const size_t bytes = static_cast<size_t>(mbs * static_cast<double>(MB));
    const size_t nvec = bytes / 16;
    size_t nbuf = POOL_BYTES / bytes;
    if (nbuf < 4) nbuf = 4;
    if (nbuf > 512) nbuf = 512;

    std::vector<void*> src(nbuf), dst(nbuf);
    bool alloc_ok = true;
    for (size_t i = 0; i < nbuf; ++i) {
      src[i] = sycl::malloc_device(bytes, q);
      dst[i] = sycl::malloc_device(bytes, q);
      if (!src[i] || !dst[i]) alloc_ok = false;
    }
    if (!alloc_ok) {
      std::fprintf(stderr, "allocation failed at %.1f MB (pool of %zu buffers)\n", mbs, nbuf);
      return 1;
    }
    for (size_t i = 0; i < nbuf; ++i)
      q.submit([&](sycl::handler& h) {
        h.parallel_for(sycl::range<1>(bytes / 4), FillRand{static_cast<u32*>(src[i]), static_cast<u32>(i * 7919u + 1u)});
      });
    q.wait();

    const std::vector<void*> no_dst;
    Best best;
    auto note = [&](const char* k, size_t wg, size_t g, const Row& r) {
      if (r.dev_gbps > best.gbps) best = Best{r.dev_gbps, wg, g, k};
    };

    for (size_t wg : {size_t(256), size_t(512)}) {
      auto grouplist = [&](size_t items) {
        std::vector<size_t> gs;
        auto add = [&](size_t g) {
          if (g && std::find(gs.begin(), gs.end(), g) == gs.end()) gs.push_back(g);
        };
        add((items + wg - 1) / wg);
        add(cu * 4);
        add(cu * 8);
        add(cu * 16);
        return gs;
      };

      for (size_t g : grouplist(nvec)) {
        Row r = run_one(q, "read_u32x4", bytes, bytes, wg, g, src, no_dst, out,
                        [&](void* s, void*) {
                          return ReadX4{static_cast<const v4*>(s), out, nvec};
                        },
                        reps);
        note("read_u32x4", wg, g, r);
      }
      for (size_t g : grouplist(nvec / 2)) {
        Row r = run_one(q, "read_u32x8", bytes, bytes, wg, g, src, no_dst, out,
                        [&](void* s, void*) {
                          return ReadX8{static_cast<const v4*>(s), out, nvec / 2};
                        },
                        reps);
        note("read_u32x8", wg, g, r);
      }
      for (size_t g : grouplist(nvec)) {
        Row r = run_one(q, "copy_u32x4", bytes, 2 * bytes, wg, g, src, dst, out,
                        [&](void* s, void* d) {
                          return CopyX4{static_cast<const v4*>(s), static_cast<v4*>(d), out,
                                        nvec};
                        },
                        reps);
        note("copy_u32x4", wg, g, r);
      }
#ifdef BW_SG
      const size_t nblocks = nvec / 16;
      for (size_t g : grouplist(nblocks * 16)) {  // one block per sub-group
        Row r = run_one(q, "read_subgroup_block", bytes, bytes, wg, g, src, no_dst, out,
                        [&](void* s, void*) {
                          return ReadSG{static_cast<u32*>(s), out, nblocks};
                        },
                        reps);
        note("read_subgroup_block", wg, g, r);
      }
#endif
    }

    std::printf("best,%.1fMB,%s,wg=%zu,groups=%zu,%.1f GB/s\n", mbs, best.kernel.c_str(),
                best.wg, best.groups, best.gbps);
    std::fflush(stdout);

    for (size_t i = 0; i < nbuf; ++i) {
      sycl::free(src[i], q);
      sycl::free(dst[i], q);
    }
  }

  sycl::free(out, q);
  return bad ? 3 : 0;
}
