#include "mq/global.h"
#include "mq/resources.h"
#include "mq/states.h"
#include "mq/string.h"

#if defined(MQ_HOSTED) || !defined(__arm__)
#include <stdio.h>
#include <stdlib.h>
#define MQ_HAVE_STDIO 1
#endif

namespace mq {

__attribute__((weak)) void fatal(const char *message)
{
#ifdef MQ_HAVE_STDIO
    fprintf(stderr, "%s\n", message);
    abort();
#else
    (void)message;
    for (;;) {}
#endif
}

__attribute__((weak)) void log(const char *message)
{
#ifdef MQ_HAVE_STDIO
    printf("qml: %s\n", message);
    fflush(stdout);
#else
    (void)message;
#endif
}

// ---------------------------------------------------------------- Color

Color Color::rgbaF(real r, real g, real b, real a)
{
    auto c = [](real v) { return int(clamp(v, 0.0f, 1.0f) * 255.0f + 0.5f); };
    return rgba(c(r), c(g), c(b), c(a));
}

Color Color::fromString(const String &str)
{
    const char *s = str.c_str();
    auto hex = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    };
    if (s[0] == '#') {
        const int n = str.length() - 1;
        uint32_t v = 0;
        for (int i = 1; i <= n; ++i) {
            int h = hex(s[i]);
            if (h < 0) return Color(0);
            v = (v << 4) | uint32_t(h);
        }
        if (n == 3)
            return rgba(int((v >> 8) & 0xf) * 17, int((v >> 4) & 0xf) * 17, int(v & 0xf) * 17);
        if (n == 6) return Color(0xff000000u | v);
        if (n == 8) return Color(v);
        return Color(0);
    }
    static const struct { const char *name; uint32_t argb; } names[] = {
        {"black", 0xff000000}, {"white", 0xffffffff}, {"red", 0xffff0000}, {"green", 0xff008000},
        {"lime", 0xff00ff00}, {"blue", 0xff0000ff}, {"yellow", 0xffffff00}, {"cyan", 0xff00ffff},
        {"magenta", 0xffff00ff}, {"gray", 0xff808080}, {"grey", 0xff808080}, {"orange", 0xffffa500},
        {"purple", 0xff800080}, {"pink", 0xffffc0cb}, {"brown", 0xffa52a2a}, {"navy", 0xff000080},
        {"teal", 0xff008080}, {"olive", 0xff808000}, {"maroon", 0xff800000}, {"gold", 0xffffd700},
        {"silver", 0xffc0c0c0}, {"crimson", 0xffdc143c}, {"tomato", 0xffff6347}, {"coral", 0xffff7f50},
        {"skyblue", 0xff87ceeb}, {"steelblue", 0xff4682b4}, {"royalblue", 0xff4169e1},
        {"turquoise", 0xff40e0d0}, {"violet", 0xffee82ee}, {"indigo", 0xff4b0082},
        {"lightgray", 0xffd3d3d3}, {"darkgray", 0xffa9a9a9}, {"transparent", 0x00000000},
    };
    for (const auto &n : names)
        if (str == n.name) return Color(n.argb);
    return Color(0);
}

Color Color::lighter(real factor) const
{
    auto c = [factor](int v) { return clamp(int(real(v) * factor + 0.5f), 0, 255); };
    return rgba(c(red()), c(green()), c(blue()), alpha());
}

Color Color::darker(real factor) const
{
    if (factor <= 0) return *this;
    return lighter(1.0f / factor);
}

// ---------------------------------------------------------------- images

namespace {
const ImageEntry *g_images = nullptr;
int g_imageCount = 0;
} // namespace

void registerImages(const ImageEntry *entries, int count)
{
    g_images = entries;
    g_imageCount = count;
}

const ImageData *imageForPath(const String &path)
{
    const char *p = path.c_str();
    // accept qrc:/ and ./ prefixes like Qt Quick does for relative sources
    static const char *const prefixes[] = {"qrc:/", "file:", "./"};
    for (const char *prefix : prefixes) {
        int i = 0;
        while (prefix[i] && p[i] == prefix[i]) ++i;
        if (!prefix[i]) p += i;
    }
    for (int i = 0; i < g_imageCount; ++i) {
        const char *a = g_images[i].path, *b = p;
        while (*a && *a == *b) { ++a; ++b; }
        if (!*a && !*b) return g_images[i].image;
    }
    return nullptr;
}

// ---------------------------------------------------------------- fonts

namespace {
const FontData *const *g_fonts = nullptr;
int g_fontCount = 0;
} // namespace

void registerFonts(const FontData *const *fonts, int count)
{
    g_fonts = fonts;
    g_fontCount = count;
}

const FontData *fontForPixelSize(int pixelSize)
{
    const FontData *best = nullptr;
    int bestDelta = 1 << 30;
    for (int i = 0; i < g_fontCount; ++i) {
        int d = int(g_fonts[i]->pixelSize) - pixelSize;
        int ad = d < 0 ? -d * 2 + 1 : d * 2;   // prefer the larger size on ties
        if (ad < bestDelta) {
            bestDelta = ad;
            best = g_fonts[i];
        }
    }
    return best;
}

const Glyph *findGlyph(const FontData &font, uint32_t cp)
{
    int lo = 0, hi = int(font.glyphCount) - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        uint32_t c = font.glyphs[mid].codepoint;
        if (c == cp) return &font.glyphs[mid];
        if (c < cp) lo = mid + 1;
        else hi = mid - 1;
    }
    return nullptr;
}

uint32_t decodeUtf8(const char *&p)
{
    uint8_t c = uint8_t(*p++);
    if (c < 0x80) return c;
    int extra = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC0 ? 1 : 0;
    uint32_t cp = c & (0x3F >> extra);
    for (int i = 0; i < extra && (uint8_t(*p) & 0xC0) == 0x80; ++i)
        cp = (cp << 6) | (uint8_t(*p++) & 0x3F);
    return cp;
}

// ---------------------------------------------------------------- states

void StateGroup::init(Property<String> *stateProperty, const State *states, int count)
{
    m_property = stateProperty;
    m_states = states;
    m_count = count;
    m_handler.init(stateProperty, this, &StateGroup::onStateChanged);
    evaluateWhen();
    if (!stateProperty->value().isEmpty()) setState(stateProperty->value());
}

void StateGroup::setTransitions(const Transition *transitions, int count)
{
    m_transitions = transitions;
    m_transitionCount = count;
}

void StateGroup::onStateChanged(void *ctx)
{
    auto *self = static_cast<StateGroup *>(ctx);
    self->setState(self->m_property->value());
}

void StateGroup::evaluateWhen()
{
    int chosen = -1;
    bool anyWhen = false;
    for (int i = 0; i < m_count; ++i) {
        if (!m_states[i].when) continue;
        anyWhen = true;
        if (m_states[i].when->value()) {
            chosen = i;
            break;
        }
    }
    if (!anyWhen) return;
    if (chosen >= 0) {
        m_whenState = chosen;
        m_property->setValue(String::lit(m_states[chosen].name));
    } else if (m_whenState >= 0) {
        // the condition that selected the current state became false
        m_whenState = -1;
        if (m_current >= 0 && m_states[m_current].when) m_property->setValue(String());
    }
}

static bool matches(const char *pattern, const char *name)
{
    if (pattern[0] == '*' && pattern[1] == 0) return true;
    // comma separated list of names
    const char *p = pattern;
    while (*p) {
        while (*p == ' ' || *p == ',') ++p;
        const char *n = name;
        while (*p && *p != ',' && *n && *p == *n) { ++p; ++n; }
        const char *q = p;
        while (*q == ' ') ++q;
        if (*n == 0 && (*q == 0 || *q == ',')) return true;
        while (*p && *p != ',') ++p;
    }
    return pattern[0] == 0 && name[0] == 0;
}

const Transition *StateGroup::findTransition(const char *from, const char *to) const
{
    for (int i = 0; i < m_transitionCount; ++i) {
        const Transition &t = m_transitions[i];
        if (matches(t.from, from) && matches(t.to, to)) return &t;
        if (t.reversible && matches(t.from, to) && matches(t.to, from)) return &t;
    }
    return nullptr;
}

void StateGroup::setState(const String &name)
{
    int next = -1;
    for (int i = 0; i < m_count; ++i)
        if (name == m_states[i].name) next = i;
    if (next == m_current) return;
    const Transition *tr = findTransition(m_current >= 0 ? m_states[m_current].name : "",
                                          next >= 0 ? m_states[next].name : "");
    if (tr)
        for (int i = 0; i < tr->count; ++i) tr->tracks[i]->capture();
    if (m_current >= 0) {
        const State &s = m_states[m_current];
        for (int i = s.count - 1; i >= 0; --i) s.changes[i]->revert();
    }
    m_current = next;
    if (next >= 0) {
        const State &s = m_states[next];
        for (int i = 0; i < s.count; ++i) s.changes[i]->apply();
    }
    if (tr)
        for (int i = 0; i < tr->count; ++i) tr->tracks[i]->start();
}

} // namespace mq
