#define DPCT_PROFILING_ENABLED
#include <sycl/sycl.hpp>
#include <dpct/dpct.hpp>
#include "strata/kernels/glm_fast.hpp"
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>
#include <algorithm>
#include <stdexcept>

static uint32_t state = 0x18af24d1u;
static float sample() { state = state * 1664525u + 1013904223u; return float(int((state >> 16) & 65535) - 32768) / 65536.0f; }
template<class T> T* device_copy(sycl::queue& q, const std::vector<T>& h) {
    T* p=sycl::malloc_device<T>(h.size(),q); if (!p) throw std::runtime_error("device allocation failed");
    q.memcpy(p,h.data(),sizeof(T)*h.size()).wait_and_throw(); return p;
}
int main(int argc, char** argv) try {
    if(argc!=2) { std::cerr << "usage: dsa_variant_parity OUTPUT\n"; return 2; }
    const int sizes[]={1,7,8,9,15,16,17,511,7130,28523,32599};
    constexpr int H=32,K=128,guard=32; constexpr float sentinel=-1337.0f;
    auto& q=dpct::get_in_order_queue();
    std::cout << "device=" << q.get_device().get_info<sycl::info::device::name>() << "\n";
    std::ofstream out(argv[1],std::ios::binary|std::ios::trunc); if(!out) throw std::runtime_error("cannot open output");
    for(int n:sizes) {
        std::vector<float> iq(H*K), pooled(size_t(n)*K), iw(H), scores(n+guard,sentinel);
        std::generate(iq.begin(),iq.end(),sample); std::generate(pooled.begin(),pooled.end(),sample); std::generate(iw.begin(),iw.end(),sample);
        auto* diq=device_copy(q,iq); auto* dp=device_copy(q,pooled); auto* dw=device_copy(q,iw); auto* ds=device_copy(q,scores);
        strata::kernels::glmf::dsa_score(diq,dp,dw,K,H,n,ds,&q,true);
        q.wait_and_throw(); q.memcpy(scores.data(),ds,scores.size()*sizeof(float)).wait_and_throw();
        for(int i=0;i<n;++i) if(!std::isfinite(scores[i])) throw std::runtime_error("nonfinite output");
        for(int i=n;i<n+guard;++i) if(scores[i]!=sentinel) throw std::runtime_error("output guard overwritten");
        if(n==1) { double reference=0; for(int h=0;h<H;++h) { double dot=0; for(int k=0;k<K;++k) dot+=double(iq[h*K+k])*pooled[k]; reference+=std::max(dot,0.0)*iw[h]; }
            if(std::abs(reference-scores[0])>1e-4) throw std::runtime_error("single-pool CPU reference mismatch"); }
        out.write(reinterpret_cast<const char*>(scores.data()),n*sizeof(float)); if(!out) throw std::runtime_error("write failed");
        std::cout << "pools=" << n << " guard=ok finite=ok\n";
        // Screening only: the same buffers remain hot, unlike a full model layer.
        if (n==7130 || n==28523 || n==32599) {
            for(int i=0;i<8;++i) strata::kernels::glmf::dsa_score(diq,dp,dw,K,H,n,ds,&q,true);
            q.wait_and_throw(); std::vector<double> us;
            for(int r=0;r<7;++r) {
                auto a=q.ext_oneapi_submit_barrier();
                for(int i=0;i<16;++i) strata::kernels::glmf::dsa_score(diq,dp,dw,K,H,n,ds,&q,true);
                auto b=q.ext_oneapi_submit_barrier(); b.wait_and_throw();
                auto t0=a.get_profiling_info<sycl::info::event_profiling::command_end>();
                auto t1=b.get_profiling_info<sycl::info::event_profiling::command_end>();
                us.push_back(double(t1-t0)/16000.0);
            }
            std::sort(us.begin(),us.end());
            std::cout << "warm-cache pools=" << n << " median_us=" << us[3] << " rounds=7 launches=16\n";
        }
        sycl::free(diq,q); sycl::free(dp,q); sycl::free(dw,q); sycl::free(ds,q);
    }
    std::cout << "PASS\n"; return 0;
} catch(const std::exception& e) { std::cerr << "FAIL: " << e.what() << "\n"; return 1; }
