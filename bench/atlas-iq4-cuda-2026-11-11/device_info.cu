#include <cuda_runtime.h>
#include <cstdio>
int main(){cudaDeviceProp p{}; auto r=cudaGetDeviceProperties(&p,0);if(r!=cudaSuccess){std::fprintf(stderr,"%s\n",cudaGetErrorString(r));return 1;}std::printf("device=%s bus_bits=%d memory_clock_khz=%d theoretical_GBps=%.3f\n",p.name,p.memoryBusWidth,p.memoryClockRate,2.0*p.memoryClockRate*1000*(p.memoryBusWidth/8)/1e9);}
