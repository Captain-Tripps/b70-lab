#include <sycl/sycl.hpp>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>
extern "C" int maya_fg_type_ok(int);
extern "C" int maya_fg_grouped(void*,int,const void*,size_t,const float*,float*,const int64_t*,int64_t,int64_t,int64_t);
int main(int argc,char** argv) try {
    if(argc!=2) { std::cerr<<"usage: xmx_bn_parity OUTPUT\n"; return 2; }
    constexpr int M=4096, NE=10; const int counts[NE]={1,15,16,17,31,32,33,63,64,65};
    std::vector<int64_t> offsets(NE+1); for(int i=0;i<NE;++i) offsets[i+1]=offsets[i]+counts[i];
    const auto rows=offsets.back(); sycl::queue q(sycl::gpu_selector_v,sycl::property::queue::in_order());
    std::cout<<"device="<<q.get_device().get_info<sycl::info::device::name>()<<" rows="<<rows<<"\n";
    std::ofstream out(argv[1],std::ios::binary|std::ios::trunc); if(!out) throw std::runtime_error("output open failed");
    for(int type: {22,18,21}) {
        const int K=type==22?4096:2048; const int block=type==22?82:type==18?98:110;
        const size_t stride=size_t(M)*(K/256)*block; std::vector<uint8_t> weights(stride*NE);
        std::mt19937 rng(1100+type); for(auto& v:weights) v=uint8_t(rng());
        for(size_t o=0;o+block<=weights.size();o+=block) { weights[o]=0; weights[o+1]=0x20; }
        std::vector<float> input(size_t(rows)*K), result(size_t(rows)*M+32,-1337.0f);
        for(size_t i=0;i<input.size();++i) input[i]=float((uint64_t(i)*2654435761ULL)%1000)*0.001f-0.5f;
        auto* w=sycl::malloc_device<uint8_t>(weights.size(),q);auto* x=sycl::malloc_device<float>(input.size(),q);auto* y=sycl::malloc_device<float>(result.size(),q);
        if(!w||!x||!y) throw std::runtime_error("allocation failed");
        q.memcpy(w,weights.data(),weights.size());q.memcpy(x,input.data(),input.size()*sizeof(float));q.memcpy(y,result.data(),result.size()*sizeof(float));q.wait_and_throw();
        if(!maya_fg_type_ok(type) || !maya_fg_grouped(&q,type,w,stride,x,y,offsets.data(),NE,M,K)) throw std::runtime_error("grouped call declined");
        q.wait_and_throw();q.memcpy(result.data(),y,result.size()*sizeof(float)).wait_and_throw();
        for(size_t i=0;i<size_t(rows)*M;++i) if(!std::isfinite(result[i])) throw std::runtime_error("nonfinite result");
        for(size_t i=size_t(rows)*M;i<result.size();++i) if(result[i]!=-1337.0f) throw std::runtime_error("output guard overwritten");
        out.write(reinterpret_cast<const char*>(result.data()),size_t(rows)*M*sizeof(float));if(!out) throw std::runtime_error("write failed");
        std::cout<<"type="<<type<<" rows="<<rows<<" finite=ok guard=ok\n";
        sycl::free(w,q);sycl::free(x,q);sycl::free(y,q);
    }
    std::cout<<"PASS\n";return 0;
} catch(const std::exception& e) { std::cerr<<"FAIL: "<<e.what()<<"\n";return 1; }
