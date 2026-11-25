// Software rasterizer drawing into an RGB565 framebuffer.
// Every primitive is clipped to the current clip rectangle (the dirty region
// being repainted), so only changed pixels are touched.
#pragma once

#include "global.h"
#include "resources.h"
#include "string.h"

namespace mq {

class Painter {
public:
    Painter(uint16_t *pixels, int width, int height, int stridePixels);

    int width() const { return m_width; }
    int height() const { return m_height; }
    void setClip(const Rect &clip);
    const Rect &clip() const { return m_clip; }

    void fillRect(const Rect &r, Color c, real opacity = 1);
    // Anti-aliased rounded rectangle with optional border.
    void fillRoundedRect(const Rect &r, int radius, Color fill, int borderWidth, Color border, real opacity = 1);
    // Draws one line of text whose baseline starts at (x, baseline).
    void drawText(int x, int baseline, const char *text, int byteCount, const FontData &font, Color c, real opacity = 1);
    void drawImage(const Rect &target, const ImageData &image, int fillMode, real opacity = 1);

    static uint16_t toRgb565(Color c) {
        return uint16_t(((c.red() & 0xf8) << 8) | ((c.green() & 0xfc) << 3) | (c.blue() >> 3));
    }
    static Color fromRgb565(uint16_t p) {
        int r = (p >> 11) & 0x1f, g = (p >> 5) & 0x3f, b = p & 0x1f;
        return Color::rgba((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2));
    }

private:
    void blendPixel(uint16_t *dst, int r, int g, int b, int alpha /*0..255*/);
    uint16_t *m_pixels;
    int m_width, m_height, m_stride;
    Rect m_clip;
};

} // namespace mq
