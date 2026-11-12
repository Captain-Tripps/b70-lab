#include <sycl/sycl.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>
extern "C" int maya_fg_type_ok(int);
extern "C" int maya_fg_grouped(void*,int,const void*,size_t,const float*,float*,const int64_t*,int64_t,int64_t,int64_t);
int main(int argc,char** argv) try {
 if(argc!=2) throw std::runtime_error("usage: xmx_iq2_reorder OUTPUT");
 constexpr int M=4096,K=4096,NE=10,B=82; const int counts[NE]={1,15,16,17,31,32,33,63,64,65};
 std::vector<int64_t> offs(NE+1);for(int i=0;i<NE;i++)offs[i+1]=offs[i]+counts[i];const int64_t rows=offs.back();
 sycl::queue q(sycl::gpu_selector_v,sycl::property::queue::in_order());
 const size_t blocks=size_t(M)*(K/256),stride=blocks*B;std::vector<uint8_t> w(stride*NE);
 std::mt19937 rng(1122);for(auto&v:w)v=uint8_t(rng());for(size_t i=0;i<w.size();i+=B){w[i]=0;w[i+1]=0x20;}
 const bool reorder=std::getenv("MAYA_FG_REORDER_IQ2")!=nullptr;
 const auto start=std::chrono::steady_clock::now();
 if(reorder){
  std::vector<uint8_t> out(w.size());
  for(int e=0;e<NE;e++)for(size_t i=0;i<blocks;i++){
   const auto* a=w.data()+e*stride+i*B;auto* z=out.data()+e*stride;
   std::memcpy(z+i*64,a+2,64);std::memcpy(z+blocks*64+i*8,a+66,8);
   std::memcpy(z+blocks*72+i*8,a+74,8);std::memcpy(z+blocks*80+i*2,a,2);
  }
  for(int e=0;e<NE;e++)for(size_t i=0;i<blocks;i++){
   const auto*a=w.data()+e*stride+i*B;const auto*z=out.data()+e*stride;
   if(std::memcmp(z+i*64,a+2,64)||std::memcmp(z+blocks*64+i*8,a+66,8)||std::memcmp(z+blocks*72+i*8,a+74,8)||std::memcmp(z+blocks*80+i*2,a,2))throw std::runtime_error("reorder mismatch");
  }
  w.swap(out);
 }
 const double prep=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
 std::vector<float> in(size_t(rows)*K),out(size_t(rows)*M+32,-1337.0f);for(size_t i=0;i<in.size();i++)in[i]=float((uint64_t(i)*2654435761ULL)%1000)*.001f-.5f;
 auto*wd=sycl::malloc_device<uint8_t>(w.size(),q);auto*xd=sycl::malloc_device<float>(in.size(),q);auto*yd=sycl::malloc_device<float>(out.size(),q);if(!wd||!xd||!yd)throw std::runtime_error("allocation failure");
 q.memcpy(wd,w.data(),w.size());q.memcpy(xd,in.data(),in.size()*4);q.memcpy(yd,out.data(),out.size()*4);q.wait_and_throw();
 auto op=[&]{if(!maya_fg_type_ok(22)||!maya_fg_grouped(&q,22,wd,stride,xd,yd,offs.data(),NE,M,K))throw std::runtime_error("declined");q.wait_and_throw();};
 for(int i=0;i<3;i++)op();
 for(int i=0;i<10;i++){auto a=std::chrono::steady_clock::now();op();double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-a).count();std::cout<<"sample_ms="<<ms<<"\n";}
 q.memcpy(out.data(),yd,out.size()*4).wait_and_throw();for(size_t i=0;i<size_t(rows)*M;i++)if(!std::isfinite(out[i]))throw std::runtime_error("nonfinite");for(size_t i=size_t(rows)*M;i<out.size();i++)if(out[i]!=-1337.f)throw std::runtime_error("guard");
 std::ofstream file(argv[1],std::ios::binary|std::ios::trunc);file.write(reinterpret_cast<const char*>(out.data()),size_t(rows)*M*4);if(!file)throw std::runtime_error("write failed");
 std::cout<<"PASS reorder="<<reorder<<" rows="<<rows<<" values="<<size_t(rows)*M<<" source_bytes="<<w.size()<<" reorder_plus_verify_ms="<<prep<<" device="<<q.get_device().get_info<sycl::info::device::name>()<<"\n";
 sycl::free(wd,q);sycl::free(xd,q);sycl::free(yd,q);return 0;
}catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}
