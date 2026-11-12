#include "ggml.h"
#include "ggml-alloc.h"
#include "ggml-backend.h"
#include "ggml-cuda.h"
#include "ggml-cpu.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <random>
#include <vector>
struct Case {
 ggml_context* ctx; ggml_tensor *a,*b,*c; ggml_cgraph* graph; ggml_backend_buffer_t buffer;
 Case(ggml_backend_t backend,ggml_type type,int64_t m,int64_t n,int64_t k,const std::vector<uint8_t>&w,const std::vector<float>&x){
  ggml_init_params p{16*1024*1024,nullptr,true};ctx=ggml_init(p);if(!ctx)throw "ctx";
  a=ggml_new_tensor_2d(ctx,type,k,m);b=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,k,n);c=ggml_mul_mat(ctx,a,b);
  graph=ggml_new_graph(ctx);ggml_build_forward_expand(graph,c);buffer=ggml_backend_alloc_ctx_tensors(ctx,backend);if(!buffer)throw "buffer";
  if(w.size()!=ggml_nbytes(a)||x.size()*sizeof(float)!=ggml_nbytes(b))throw "shape";
  ggml_backend_tensor_set(a,w.data(),0,w.size());ggml_backend_tensor_set(b,x.data(),0,x.size()*sizeof(float));
 }
 ~Case(){ggml_backend_buffer_free(buffer);ggml_free(ctx);}
};
int main(int argc,char**argv)try{
 if(argc!=5)throw "args: iq4_xs|iq4_nl m n k";
 ggml_type type=std::string(argv[1])=="iq4_xs"?GGML_TYPE_IQ4_XS:std::string(argv[1])=="iq4_nl"?GGML_TYPE_IQ4_NL:GGML_TYPE_COUNT;
 int64_t m=std::atoll(argv[2]),n=std::atoll(argv[3]),k=std::atoll(argv[4]);if(type==GGML_TYPE_COUNT||m<=0||n<=0||k<=0||k%256)throw "invalid shape";
 const size_t bytes=(size_t(m)*k/ggml_blck_size(type))*ggml_type_size(type),block=ggml_type_size(type);
 std::vector<uint8_t>w(bytes);std::mt19937 rng(31998);for(auto&v:w)v=uint8_t(rng());for(size_t i=0;i<bytes;i+=block){w[i]=0;w[i+1]=0x28;}
 std::vector<float>x(size_t(k)*n);for(size_t i=0;i<x.size();i++)x[i]=float((i*2654435761ULL)%1000)*0.001f-0.5f;
 auto gpu=ggml_backend_cuda_init(0);if(!gpu)throw "cuda"; std::vector<float> got(size_t(m)*n),ref(got.size()); double us=0;
 {Case test(gpu,type,m,n,k,w,x);for(int i=0;i<4;i++)if(ggml_backend_graph_compute(gpu,test.graph)!=GGML_STATUS_SUCCESS)throw "warmup";
  auto t=std::chrono::steady_clock::now();for(int i=0;i<100;i++)if(ggml_backend_graph_compute_async(gpu,test.graph)!=GGML_STATUS_SUCCESS)throw "compute";ggml_backend_synchronize(gpu);
  us=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-t).count()/100;
  ggml_backend_tensor_get(test.c,got.data(),0,got.size()*sizeof(float));}
 ggml_backend_free(gpu);
 auto cpu=ggml_backend_cpu_init();if(!cpu)throw "cpu";ggml_backend_cpu_set_n_threads(cpu,2);
 {Case test(cpu,type,m,n,k,w,x);if(ggml_backend_graph_compute(cpu,test.graph)!=GGML_STATUS_SUCCESS)throw "cpu compute";ggml_backend_tensor_get(test.c,ref.data(),0,ref.size()*sizeof(float));}ggml_backend_free(cpu);
 double err=0,den=0,maxabs=0;for(size_t i=0;i<got.size();i++){if(!std::isfinite(got[i])||!std::isfinite(ref[i]))throw "nonfinite";double d=double(got[i])-ref[i];err+=d*d;den+=double(ref[i])*ref[i];maxabs=std::max(maxabs,std::abs(d));}
 const double nmse=err/std::max(den,1e-30);std::cout<<"type="<<argv[1]<<" m="<<m<<" n="<<n<<" k="<<k<<" us="<<us<<" weight_bytes="<<bytes<<" cpu_nmse="<<nmse<<" max_abs="<<maxabs<<"\n";
 if(nmse>5e-4)throw "parity threshold";return 0;
}catch(const char*e){std::cerr<<"FAIL "<<e<<"\n";return 1;}
