// MicroQuick - a small Qt Quick-like UI runtime for microcontrollers.
// global.h: basic types shared by the whole runtime.
//
// The runtime is written in C++17 without exceptions, RTTI or dynamic memory
// allocation: every object lives in static storage or inside the generated
// application object.
#pragma once

#include <stdint.h>
#include <stddef.h>

#ifndef MQ_STRING_CAPACITY
#define MQ_STRING_CAPACITY 64          // bytes (UTF-8) stored inline in mq::String
#endif
#ifndef MQ_DEFAULT_LINK_POOL
#define MQ_DEFAULT_LINK_POOL 256       // dependency links when the app registers no pool
#endif
#ifndef MQ_MAX_DIRTY_RECTS
#define MQ_MAX_DIRTY_RECTS 4           // dirty rectangles tracked per frame
#endif

namespace mq {

using real = float;

// Hook for fatal errors (binding loops, dependency overflow...). Platforms may
// override the weak default which loops forever / aborts.
void fatal(const char *message);
// Debug log (console.log). Weak default prints with printf on hosted builds.
void log(const char *message);

template <typename T> constexpr T min(T a, T b) { return a < b ? a : b; }
template <typename T> constexpr T max(T a, T b) { return a > b ? a : b; }
template <typename T> constexpr T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

struct Rect {
    int x = 0, y = 0, w = 0, h = 0;

    constexpr Rect() = default;
    constexpr Rect(int x_, int y_, int w_, int h_) : x(x_), y(y_), w(w_), h(h_) {}

    constexpr bool isEmpty() const { return w <= 0 || h <= 0; }
    constexpr int right() const { return x + w; }   // exclusive
    constexpr int bottom() const { return y + h; }  // exclusive
    constexpr bool contains(int px, int py) const {
        return px >= x && py >= y && px < x + w && py < y + h;
    }
    Rect intersected(const Rect &o) const {
        int l = max(x, o.x), t = max(y, o.y);
        int r = min(right(), o.right()), b = min(bottom(), o.bottom());
        if (r <= l || b <= t) return Rect();
        return Rect(l, t, r - l, b - t);
    }
    Rect united(const Rect &o) const {
        if (isEmpty()) return o;
        if (o.isEmpty()) return *this;
        int l = min(x, o.x), t = min(y, o.y);
        int r = max(right(), o.right()), b = max(bottom(), o.bottom());
        return Rect(l, t, r - l, b - t);
    }
    bool intersects(const Rect &o) const { return !intersected(o).isEmpty(); }
    bool operator==(const Rect &o) const { return x == o.x && y == o.y && w == o.w && h == o.h; }
    bool operator!=(const Rect &o) const { return !(*this == o); }
};

// 32-bit non-premultiplied ARGB color, like QColor's QRgb.
struct Color {
    uint32_t argb = 0xff000000u;

    constexpr Color() = default;
    constexpr explicit Color(uint32_t v) : argb(v) {}
    static constexpr Color rgba(int r, int g, int b, int a = 255) {
        return Color((uint32_t(a & 0xff) << 24) | (uint32_t(r & 0xff) << 16) |
                     (uint32_t(g & 0xff) << 8) | uint32_t(b & 0xff));
    }
    static Color rgbaF(real r, real g, real b, real a = 1);
    // Parses "#rgb", "#rrggbb", "#aarrggbb" or a common color name at run time
    // (used when a color comes from a model role). Unknown -> transparent.
    static Color fromString(const class String &s);
    constexpr int alpha() const { return int(argb >> 24); }
    constexpr int red() const { return int((argb >> 16) & 0xff); }
    constexpr int green() const { return int((argb >> 8) & 0xff); }
    constexpr int blue() const { return int(argb & 0xff); }
    Color lighter(real factor = 1.5f) const;
    Color darker(real factor = 2.0f) const;
    constexpr bool operator==(const Color &o) const { return argb == o.argb; }
    constexpr bool operator!=(const Color &o) const { return argb != o.argb; }
};

} // namespace mq
