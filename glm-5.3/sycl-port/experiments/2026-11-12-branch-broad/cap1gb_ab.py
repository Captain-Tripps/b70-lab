import ctypes, hashlib, json, os, pathlib, subprocess, sys, threading, time, urllib.request

# Variant of broad_ab.py with a 1 GiB RAM-slot byte cap and identical prompt text for two image payloads.
source_path=pathlib.Path(__file__).with_name('broad_ab.py')
source=source_path.read_text(encoding='utf8')
source=source.replace('codex-slot-branch-broad-20261112','codex-slot-branch-cap1gb-20261112')
source=source.replace("STRATA_GLM_SLOT_RAM_GB']='12'", "STRATA_GLM_SLOT_RAM_GB']='1'")
source=source.replace("('image-llama0','llama0-logo.png','Describe the logo briefly.'),('image-llama1','llama1-logo.png','Describe this image briefly.')", "('image-llama0','llama0-logo.png','Describe this image briefly.'),('image-llama1','llama1-logo.png','Describe this image briefly.')")
source=source.replace("  for label,name,prompt in [('image-llama0'", "  image_payloads={}\n  for label,name,prompt in [('image-llama0'")
source=source.replace("   req(label,im)\n  req('B-after-images',b);req('truncated-context'", "   req(label,im)\n   image_payloads[label]=im\n  req('image-llama0-repeat',image_payloads['image-llama0'])\n  req('B-after-images',b);req('truncated-context'")
exec(compile(source,str(source_path),'exec'))
