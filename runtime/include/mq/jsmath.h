// Helpers implementing JavaScript semantics needed by generated code.
#pragma once

#include <math.h>
#include "global.h"
#include "string.h"
#include <initializer_list>

namespace mq {

// Read-only array stored in flash (JS array literals, list<T> properties,
// array models). Out of range reads return a default value.
template <typename T>
struct ConstArray {
    const T *data = nullptr;
    int count = 0;
    constexpr ConstArray() = default;
    constexpr ConstArray(const T *d, int n) : data(d), count(n) {}
    T at(int i) const { return (i >= 0 && i < count) ? data[i] : T(); }
    int size() const { return count; }
    bool operator==(const ConstArray &o) const { return data == o.data && count == o.count; }
};

// Storage for a Loader: big enough and aligned for any of the candidates.
template <typename... Ts>
struct LoaderStorage {
    static constexpr size_t maxSize() {
        size_t m = 1;
        for (size_t s : {sizeof(Ts)...}) m = s > m ? s : m;
        return m;
    }
    alignas(Ts...) unsigned char data[maxSize()];
};

namespace js {

// ---- ListModel rows stored in fixed arrays (no heap)
template <typename R, int N>
bool listInsert(R (&rows)[N], int &size, int at, const R &row)
{
    if (size >= N) {
        mq::log("ListModel: capacity reached, row ignored");
        return false;
    }
    at = at < 0 ? 0 : (at > size ? size : at);
    for (int i = size; i > at; --i) rows[i] = rows[i - 1];
    rows[at] = row;
    ++size;
    return true;
}
template <typename R, int N>
void listRemove(R (&rows)[N], int &size, int at, int count = 1)
{
    if (at < 0 || at >= size || count <= 0) return;
    if (at + count > size) count = size - at;
    for (int i = at; i + count < size; ++i) rows[i] = rows[i + count];
    for (int i = size - count; i < size; ++i) rows[i] = R();
    size -= count;
}
template <typename R, int N>
void listMove(R (&rows)[N], int size, int from, int to, int count = 1)
{
    if (from < 0 || to < 0 || count <= 0 || from + count > size || to + count > size || from == to) return;
    for (int k = 0; k < count; ++k) {
        if (from < to) {
            R tmp = rows[from];
            for (int i = from; i < to + count - 1; ++i) rows[i] = rows[i + 1];
            rows[to + count - 1] = tmp;
        } else {
            R tmp = rows[from + count - 1];
            for (int i = from + count - 1; i > to; --i) rows[i] = rows[i - 1];
            rows[to] = tmp;
        }
    }
}
template <typename R, int N>
R &listAt(R (&rows)[N], int size, int i)
{
    static R scratch;
    if (i >= 0 && i < size) return rows[i];
    scratch = R();
    return scratch;
}


constexpr real kPi = 3.14159265358979f;   // not "PI": Arduino defines a PI macro

inline real div(real a, real b) { return a / b; }      // JS '/' is always floating point
inline int mod(int a, int b) { return b == 0 ? 0 : a % b; }
inline real mod(real a, real b) { return fmodf(a, b); }

inline int floor(real v) { return int(floorf(v)); }
inline int ceil(real v) { return int(ceilf(v)); }
inline int round(real v) { return int(floorf(v + 0.5f)); }  // JS rounds .5 up
inline int abs(int v) { return v < 0 ? -v : v; }
inline real abs(real v) { return fabsf(v); }
inline int min(int a, int b) { return a < b ? a : b; }
inline real min(real a, real b) { return a < b ? a : b; }
inline int max(int a, int b) { return a > b ? a : b; }
inline real max(real a, real b) { return a > b ? a : b; }
inline real sqrt(real v) { return sqrtf(v); }
inline real sin(real v) { return sinf(v); }
inline real cos(real v) { return cosf(v); }
inline real tan(real v) { return tanf(v); }
inline real atan2(real y, real x) { return atan2f(y, x); }
inline real pow(real a, real b) { return powf(a, b); }

// Number.prototype.toFixed
inline String toFixed(real v, int decimals) { return String::number(v, decimals); }

// Truthiness for `if (string)` etc.
inline bool truthy(bool v) { return v; }
inline bool truthy(int v) { return v != 0; }
inline bool truthy(real v) { return v != 0 && v == v; }
inline bool truthy(const String &s) { return !s.isEmpty(); }

} // namespace js
} // namespace mq
