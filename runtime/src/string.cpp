#include "mq/string.h"

namespace mq {

namespace {
int cstrLen(const char *s)
{
    int n = 0;
    while (s[n]) ++n;
    return n;
}
} // namespace

String::String(const char *s)
{
    m_data[0] = 0;
    if (s) append(s);
}

String String::lit(const char *s)
{
    String r;
    if (!s) return r;
    r.m_ext = s;
    r.m_len = uint16_t(cstrLen(s));
    return r;
}

void String::detachExt()
{
    if (!m_ext) return;
    const char *e = m_ext;
    int len = m_len;
    m_ext = nullptr;
    m_len = 0;
    m_data[0] = 0;
    append(e, len);
}

String &String::append(const char *s, int len)
{
    if (len < 0) len = cstrLen(s);
    if (len == 0) return *this;
    if (m_ext) {
        if (m_len == 0) {            // empty literal: just drop it
            m_ext = nullptr;
            m_data[0] = 0;
        } else {
            detachExt();
        }
    }
    int room = MQ_STRING_CAPACITY - 1 - m_len;
    if (len > room) {
        len = room;
        // do not cut a UTF-8 sequence in the middle
        while (len > 0 && (uint8_t(s[len]) & 0xC0) == 0x80) --len;
    }
    for (int i = 0; i < len; ++i) m_data[m_len + i] = s[i];
    m_len = uint16_t(m_len + len);
    m_data[m_len] = 0;
    return *this;
}

int String::charCount() const
{
    const char *d = c_str();
    int n = 0;
    for (int i = 0; i < m_len; ++i)
        if ((uint8_t(d[i]) & 0xC0) != 0x80) ++n;
    return n;
}

bool String::operator==(const String &o) const
{
    if (m_len != o.m_len) return false;
    const char *a = c_str(), *b = o.c_str();
    if (a == b) return true;
    for (int i = 0; i < m_len; ++i)
        if (a[i] != b[i]) return false;
    return true;
}

bool String::operator==(const char *s) const
{
    const char *d = c_str();
    int i = 0;
    for (; i < m_len; ++i)
        if (s[i] != d[i]) return false;
    return s[i] == 0;
}

String String::number(int v)
{
    char buf[12];
    int pos = 11;
    buf[pos] = 0;
    uint32_t u = v < 0 ? uint32_t(-(int64_t)v) : uint32_t(v);
    do {
        buf[--pos] = char('0' + u % 10);
        u /= 10;
    } while (u);
    if (v < 0) buf[--pos] = '-';
    return String(buf + pos);
}

String String::number(real v, int decimals)
{
    if (v != v) return String("NaN");
    if (v > 2e9f || v < -2e9f) return String(v > 0 ? "Infinity" : "-Infinity");
    bool trim = decimals < 0;
    if (trim) decimals = 6;
    if (decimals > 6) decimals = 6;
    bool neg = v < 0;
    if (neg) v = -v;
    uint32_t scale = 1;
    for (int i = 0; i < decimals; ++i) scale *= 10;
    // round to the requested number of decimals
    double scaled = double(v) * scale + 0.5;
    uint64_t total = uint64_t(scaled);
    uint32_t ip = uint32_t(total / scale);
    uint32_t fp = uint32_t(total % scale);
    String s;
    if (neg && (ip || fp)) s.append("-");
    s += number(int(ip));
    if (decimals > 0) {
        char frac[8];
        for (int i = decimals - 1; i >= 0; --i) {
            frac[i] = char('0' + fp % 10);
            fp /= 10;
        }
        int n = decimals;
        if (trim)
            while (n > 0 && frac[n - 1] == '0') --n;
        if (n > 0) {
            s.append(".");
            s.append(frac, n);
        }
    }
    return s;
}

int String::toInt(bool *ok) const
{
    const char *m_data = c_str();
    int i = 0, sign = 1, v = 0;
    while (i < m_len && m_data[i] == ' ') ++i;
    if (i < m_len && (m_data[i] == '-' || m_data[i] == '+')) sign = m_data[i++] == '-' ? -1 : 1;
    int start = i;
    while (i < m_len && m_data[i] >= '0' && m_data[i] <= '9') v = v * 10 + (m_data[i++] - '0');
    if (ok) *ok = i > start;
    return v * sign;
}

real String::toReal(bool *ok) const
{
    const char *m_data = c_str();
    int i = 0;
    real sign = 1, v = 0;
    while (i < m_len && m_data[i] == ' ') ++i;
    if (i < m_len && (m_data[i] == '-' || m_data[i] == '+')) sign = m_data[i++] == '-' ? -1.0f : 1.0f;
    int start = i;
    while (i < m_len && m_data[i] >= '0' && m_data[i] <= '9') v = v * 10 + real(m_data[i++] - '0');
    if (i < m_len && m_data[i] == '.') {
        ++i;
        real f = 0.1f;
        while (i < m_len && m_data[i] >= '0' && m_data[i] <= '9') {
            v += f * real(m_data[i++] - '0');
            f *= 0.1f;
        }
    }
    if (ok) *ok = i > start;
    return v * sign;
}

} // namespace mq
