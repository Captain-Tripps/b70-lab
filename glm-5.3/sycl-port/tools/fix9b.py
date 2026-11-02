import sys
for p in sys.argv[1:]:
    s = open(p, newline="", encoding="utf-8", errors="surrogateescape").read()
    s = s.replace("F->md.resp = sycl::malloc_device(sizeof(gf::MoeResponse), dpct::get_in_order_queue());",
                  "void* resp_m = sycl::malloc_device(sizeof(gf::MoeResponse), dpct::get_in_order_queue());   // (md.resp is const void*)")
    s = s.replace("if (F->md.resp == nullptr) { err = \"glm fast: the routing response mirror did not allocate\"; return false; }",
                  "if (resp_m == nullptr) { err = \"glm fast: the routing response mirror did not allocate\"; return false; }")
    s = s.replace("dpct::get_in_order_queue().memset(F->md.resp, 0, sizeof(gf::MoeResponse)).wait();",
                  "dpct::get_in_order_queue().memset(resp_m, 0, sizeof(gf::MoeResponse)).wait();\n    F->md.resp = resp_m;")
    s = s.replace("sycl_publish_resp(fast_->cs, F->md.resp, Rp,", "sycl_publish_resp(fast_->cs, const_cast<void*>(F->md.resp), Rp,")
    s = s.replace("sycl_publish_word(fast_->cs, (char*) F->md.resp +", "sycl_publish_word(fast_->cs, (char*) const_cast<void*>(F->md.resp) +")
    open(p, "w", newline="", encoding="utf-8", errors="surrogateescape").write(s)
    print(p, s.count("resp_m"), s.count("const_cast<void*>(F->md.resp)"))
