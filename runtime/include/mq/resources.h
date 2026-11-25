// Compiled resources: pre-rasterized fonts and pre-converted images.
// These structures are generated at build time by `mqassets` (a Qt host tool)
// and live in flash (const data).
#pragma once

#include "global.h"

namespace mq {

struct Glyph {
    uint32_t codepoint;
    int16_t left;        // x offset from pen position to bitmap left edge
    int16_t top;         // y offset from baseline to bitmap top edge (negative = above)
    uint8_t width;
    uint8_t height;
    uint8_t advance;
    uint32_t offset;     // index of the first alpha byte in FontData::alpha
};

struct FontData {
    uint16_t pixelSize;
    int16_t ascent;
    int16_t descent;
    int16_t lineHeight;
    uint16_t glyphCount;
    const Glyph *glyphs;     // sorted by codepoint
    const uint8_t *alpha;    // 8-bit coverage, row-major per glyph
};

enum class PixelFormat : uint8_t { RGB565 = 0, ARGB8888 = 1 };

struct ImageData {
    uint16_t width;
    uint16_t height;
    PixelFormat format;
    const void *pixels;      // uint16_t[] (RGB565) or uint32_t[] (ARGB8888, non premultiplied)
};

// Image table: lets an Image source be computed at run time
// (e.g. "icons/" + name + ".png"). Registered by the generated code.
struct ImageEntry {
    const char *path;          // relative to the main QML file
    const ImageData *image;
};
void registerImages(const ImageEntry *entries, int count);
const ImageData *imageForPath(const class String &path);   // nullptr if unknown

// Font registry (fonts are registered by the generated application code).
void registerFonts(const FontData *const *fonts, int count);
const FontData *fontForPixelSize(int pixelSize);   // nearest available size
const Glyph *findGlyph(const FontData &font, uint32_t codepoint);

// UTF-8 decoding helper: returns code point and advances *p.
uint32_t decodeUtf8(const char *&p);

} // namespace mq
