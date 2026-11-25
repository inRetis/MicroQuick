// Minimal test helpers (no dependency, works without exceptions).
#pragma once
#include <cstdio>
#include <cstdlib>

inline int &mq_test_failures() { static int n = 0; return n; }

#define CHECK(cond) do { if (!(cond)) { \
    std::printf("%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); ++mq_test_failures(); } } while (0)
#define CHECK_EQ(a, b) do { auto va_ = (a); auto vb_ = (b); if (!(va_ == vb_)) { \
    std::printf("%s:%d: CHECK_EQ failed: %s == %s\n", __FILE__, __LINE__, #a, #b); ++mq_test_failures(); } } while (0)
#define TEST_MAIN_END() do { if (mq_test_failures()) { std::printf("%d failure(s)\n", mq_test_failures()); return 1; } \
    std::printf("all tests passed\n"); return 0; } while (0)
