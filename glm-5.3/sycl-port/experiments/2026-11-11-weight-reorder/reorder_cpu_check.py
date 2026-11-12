import random
r=random.Random(31998)
for n in (1,2,7,16,257,1024):
 blocks=[bytes(r.randrange(256) for _ in range(82)) for _ in range(n)]
 packed=bytearray(82*n)
 for i,x in enumerate(blocks):
  packed[64*i:64*i+64]=x[2:66];packed[64*n+8*i:64*n+8*i+8]=x[66:74]
  packed[72*n+8*i:72*n+8*i+8]=x[74:82];packed[80*n+2*i:80*n+2*i+2]=x[:2]
 for i,x in enumerate(blocks):
  reconstructed=bytes(packed[80*n+2*i:80*n+2*i+2]+packed[64*i:64*i+64]+packed[64*n+8*i:64*n+8*i+8]+packed[72*n+8*i:72*n+8*i+8])
  assert reconstructed==x,(n,i)
 print('blocks',n,'byte_roundtrip_ok',flush=True)
