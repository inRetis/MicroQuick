// mq::String: fixed-capacity UTF-8 string stored inline (no heap).
// Text longer than MQ_STRING_CAPACITY-1 bytes is truncated on a UTF-8
// character boundary.
#pragma once

#include "global.h"

namespace mq {

class String {
public:
    String() { m_data[0] = 0; }
    String(const char *s);
    String(const String &) = default;
    String &operator=(const String &) = default;

    // References a string with static storage (literal / flash) without
    // copying it: not limited by MQ_STRING_CAPACITY.
    static String lit(const char *s);

    static String number(int v);
    static String number(real v, int decimals = -1);   // -1: up to 6 significant decimals

    const char *c_str() const { return m_ext ? m_ext : m_data; }
    int length() const { return m_len; }               // bytes
    int charCount() const;                             // UTF-8 code points (JS .length)
    bool isEmpty() const { return m_len == 0; }

    String &append(const char *s, int len = -1);
    String &operator+=(const String &o) { return append(o.c_str(), o.m_len); }
    String &operator+=(const char *s) { return append(s); }

    bool operator==(const String &o) const;
    bool operator!=(const String &o) const { return !(*this == o); }
    bool operator==(const char *s) const;
    bool operator!=(const char *s) const { return !(*this == s); }

    int toInt(bool *ok = nullptr) const;
    real toReal(bool *ok = nullptr) const;

private:
    void detachExt();
    const char *m_ext = nullptr;
    char m_data[MQ_STRING_CAPACITY];
    uint16_t m_len = 0;
};

inline String operator+(String a, const String &b) { return a += b; }
inline String operator+(String a, const char *b) { return a += b; }
inline String operator+(String a, int b) { return a += String::number(b); }
inline String operator+(String a, real b) { return a += String::number(b); }
inline String operator+(String a, double b) { return a += String::number(real(b)); }
inline String operator+(String a, bool b) { return a += (b ? "true" : "false"); }
inline String operator+(int a, const String &b) { return String::number(a) + b; }
inline String operator+(real a, const String &b) { return String::number(a) + b; }
inline String operator+(bool a, const String &b) { return String(a ? "true" : "false") + b; }

// Helpers used by generated code (JS semantics for .toString()/concat).
inline String toString(const String &s) { return s; }
inline String toString(int v) { return String::number(v); }
inline String toString(real v) { return String::number(v); }
inline String toString(bool v) { return String(v ? "true" : "false"); }

} // namespace mq
