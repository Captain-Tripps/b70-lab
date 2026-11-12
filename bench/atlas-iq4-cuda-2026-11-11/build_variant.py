import pathlib, shlex, subprocess

src = pathlib.Path('<atlas-home>/llama.cpp-v0.9.0')
work = pathlib.Path('<atlas-home>/experiments/codex-atlas-iq4-20261111')
build = src / 'build-cuda/ggml/src/ggml-cuda'
out = work / 'variant-2warp'
out.mkdir(exist_ok=True)
original = (src / 'ggml/src/ggml-cuda/mmvq.cu').read_text()
needle = 'if (table_id == MMVQ_PARAMETERS_GENERIC) {\n        switch (ncols_dst) {'
replacement = 'if (table_id == MMVQ_PARAMETERS_GENERIC) {\n        if (type == GGML_TYPE_IQ4_NL && ncols_dst == 4) return 2;\n        switch (ncols_dst) {'
assert original.count(needle) == 1
(out / 'mmvq.cu').write_text(original.replace(needle, replacement))
flags = (build / 'CMakeFiles/ggml-cuda.dir/flags.make').read_text()
def setting(name):
    return next(line.split(' = ', 1)[1] for line in flags.splitlines() if line.startswith(name + ' = '))
cmd = ['/usr/bin/nvcc', '-forward-unknown-to-host-compiler']
cmd += shlex.split(setting('CUDA_DEFINES')) + shlex.split(setting('CUDA_INCLUDES')) + shlex.split(setting('CUDA_FLAGS'))
cmd += ['-I' + str(src / 'ggml/src/ggml-cuda'), '-x', 'cu', '-c', str(out / 'mmvq.cu'), '-o', str(out / 'mmvq.cu.o')]
subprocess.run(cmd, cwd=build, check=True)
obj = (build / 'CMakeFiles/ggml-cuda.dir/objects1.rsp').read_text()
needle = 'CMakeFiles/ggml-cuda.dir/mmvq.cu.o'
assert obj.count(needle) == 1
(out / 'objects.rsp').write_text(obj.replace(needle, str(out / 'mmvq.cu.o')))
cmd = ['/usr/lib/nvidia-cuda-toolkit/bin/g++', '-fPIC', '-shared', '-Wl,-soname,libggml-cuda.so.0', '-o', str(out / 'libggml-cuda.so.0.29.0'), '@' + str(out / 'objects.rsp'), '@CMakeFiles/ggml-cuda.dir/linkLibs.rsp', '-L/usr/lib/x86_64-linux-gnu/stubs', '-L/usr/lib/x86_64-linux-gnu']
subprocess.run(cmd, cwd=build, check=True)
(out / 'libggml-cuda.so.0').symlink_to('libggml-cuda.so.0.29.0')
(out / 'libggml-cuda.so').symlink_to('libggml-cuda.so.0')
print('Variant built:', out, flush=True)
