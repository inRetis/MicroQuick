#include "mq/painter.h"
#include <math.h>

namespace mq {

Painter::Painter(uint16_t *pixels, int width, int height, int stridePixels)
    : m_pixels(pixels), m_width(width), m_height(height), m_stride(stridePixels),
      m_clip(0, 0, width, height)
{
}

void Painter::setClip(const Rect &clip)
{
    m_clip = clip.intersected(Rect(0, 0, m_width, m_height));
}

inline void Painter::blendPixel(uint16_t *dst, int r, int g, int b, int a)
{
    if (a <= 0) return;
    if (a >= 255) {
        *dst = uint16_t(((r & 0xf8) << 8) | ((g & 0xfc) << 3) | (b >> 3));
        return;
    }
    uint16_t d = *dst;
    int dr = (d >> 11) & 0x1f, dg = (d >> 5) & 0x3f, db = d & 0x1f;
    dr = (dr << 3) | (dr >> 2);
    dg = (dg << 2) | (dg >> 4);
    db = (db << 3) | (db >> 2);
    int ia = 255 - a;
    int nr = (r * a + dr * ia + 127) / 255;
    int ng = (g * a + dg * ia + 127) / 255;
    int nb = (b * a + db * ia + 127) / 255;
    *dst = uint16_t(((nr & 0xf8) << 8) | ((ng & 0xfc) << 3) | (nb >> 3));
}

void Painter::fillRect(const Rect &r, Color c, real opacity)
{
    Rect R = r.intersected(m_clip);
    if (R.isEmpty()) return;
    int a = int(real(c.alpha()) * opacity + 0.5f);
    if (a <= 0) return;
    if (a >= 255) {
        uint16_t v = toRgb565(c);
        for (int y = R.y; y < R.bottom(); ++y) {
            uint16_t *row = m_pixels + y * m_stride;
            for (int x = R.x; x < R.right(); ++x) row[x] = v;
        }
        return;
    }
    int cr = c.red(), cg = c.green(), cb = c.blue();
    for (int y = R.y; y < R.bottom(); ++y) {
        uint16_t *row = m_pixels + y * m_stride;
        for (int x = R.x; x < R.right(); ++x) blendPixel(row + x, cr, cg, cb, a);
    }
}

namespace {

// Coverage (0..1) of pixel (px,py) by a rounded rectangle [l,r)x[t,b).
inline float coverage(int px, int py, int l, int t, int r, int b, int rad)
{
    float cx = float(px) + 0.5f, cy = float(py) + 0.5f;
    if (rad <= 0)
        return (cx >= float(l) && cx <= float(r) && cy >= float(t) && cy <= float(b)) ? 1.0f : 0.0f;
    float fr = float(rad);
    float dx = max(max(float(l) + fr - cx, cx - (float(r) - fr)), 0.0f);
    float dy = max(max(float(t) + fr - cy, cy - (float(b) - fr)), 0.0f);
    if (dx == 0.0f && dy == 0.0f) return 1.0f;
    float d = sqrtf(dx * dx + dy * dy);
    return clamp(fr - d + 0.5f, 0.0f, 1.0f);
}

} // namespace

void Painter::fillRoundedRect(const Rect &r, int radius, Color fill, int bw, Color border, real opacity)
{
    Rect R = r.intersected(m_clip);
    if (R.isEmpty() || opacity <= 0) return;
    int half = min(r.w, r.h) / 2;
    radius = clamp(radius, 0, half);
    bw = clamp(bw, 0, half);

    const int L = r.x, T = r.y, Rr = r.right(), B = r.bottom();
    const int Li = L + bw, Ti = T + bw, Ri = Rr - bw, Bi = B - bw;
    const int ri = max(radius - bw, 0);
    const int e = max(radius, bw);            // width of the per-pixel edge zone

    const float fa = float(fill.alpha()) / 255.0f, ba = float(border.alpha()) / 255.0f;
    const int fillA = int(float(fill.alpha()) * opacity + 0.5f);
    const int borderA = int(float(border.alpha()) * opacity + 0.5f);
    const int fr = fill.red(), fg = fill.green(), fb = fill.blue();
    const int br = border.red(), bg = border.green(), bb = border.blue();

    auto span = [&](uint16_t *row, int x0, int x1, bool isBorder) {
        x0 = max(x0, R.x);
        x1 = min(x1, R.right());
        if (isBorder) {
            for (int x = x0; x < x1; ++x) blendPixel(row + x, br, bg, bb, borderA);
        } else {
            for (int x = x0; x < x1; ++x) blendPixel(row + x, fr, fg, fb, fillA);
        }
    };
    auto pixel = [&](uint16_t *row, int x, int y) {
        float co = coverage(x, y, L, T, Rr, B, radius);
        if (co <= 0.0f) return;
        float ci = bw > 0 ? coverage(x, y, Li, Ti, Ri, Bi, ri) : co;
        float af = fa * ci;
        float ab = ba * max(co - ci, 0.0f);
        float at = af + ab;
        if (at <= 0.0f) return;
        int cr = int((float(fr) * af + float(br) * ab) / at);
        int cg = int((float(fg) * af + float(bg) * ab) / at);
        int cb = int((float(fb) * af + float(bb) * ab) / at);
        blendPixel(row + x, cr, cg, cb, int(at * opacity * 255.0f + 0.5f));
    };

    for (int y = R.y; y < R.bottom(); ++y) {
        uint16_t *row = m_pixels + y * m_stride;
        bool cornerRow = y < T + e || y >= B - e;
        if (!cornerRow) {
            span(row, L, Li, true);
            span(row, Li, Ri, false);
            span(row, Ri, Rr, true);
            continue;
        }
        bool borderBand = y < Ti || y >= Bi;
        int leftEnd = min(L + e, Rr), rightStart = max(Rr - e, leftEnd);
        for (int x = max(L, R.x); x < min(leftEnd, R.right()); ++x) pixel(row, x, y);
        span(row, leftEnd, rightStart, borderBand);
        for (int x = max(rightStart, R.x); x < min(Rr, R.right()); ++x) pixel(row, x, y);
    }
}

void Painter::drawText(int x, int baseline, const char *text, int bytes, const FontData &font, Color c, real opacity)
{
    const int ca = int(float(c.alpha()) * opacity + 0.5f);
    if (ca <= 0) return;
    const int cr = c.red(), cg = c.green(), cb = c.blue();
    const char *s = text, *end = text + bytes;
    while (s < end) {
        uint32_t cp = decodeUtf8(s);
        const Glyph *g = findGlyph(font, cp);
        if (!g) {
            x += font.pixelSize / 3;
            continue;
        }
        Rect gr(x + g->left, baseline + g->top, g->width, g->height);
        Rect R = gr.intersected(m_clip);
        if (!R.isEmpty()) {
            const uint8_t *alpha = font.alpha + g->offset;
            for (int yy = R.y; yy < R.bottom(); ++yy) {
                const uint8_t *src = alpha + (yy - gr.y) * g->width - gr.x;
                uint16_t *row = m_pixels + yy * m_stride;
                for (int xx = R.x; xx < R.right(); ++xx) {
                    int a = src[xx];
                    if (a) blendPixel(row + xx, cr, cg, cb, (a * ca + 127) / 255);
                }
            }
        }
        x += g->advance;
    }
}

void Painter::drawImage(const Rect &target, const ImageData &img, int fillMode, real opacity)
{
    Rect R = target.intersected(m_clip);
    if (R.isEmpty() || img.width == 0 || img.height == 0) return;
    const int op = int(opacity * 255.0f + 0.5f);
    if (op <= 0) return;
    const bool stretch = fillMode == 0;
    const bool tile = fillMode == 2;
    if (fillMode == 1) // Pad: unscaled, clipped to the image size
        R = R.intersected(Rect(target.x, target.y, img.width, img.height));
    for (int y = R.y; y < R.bottom(); ++y) {
        int sy = y - target.y;
        if (stretch) sy = sy * img.height / max(target.h, 1);
        else if (tile) sy %= img.height;
        uint16_t *row = m_pixels + y * m_stride;
        for (int x = R.x; x < R.right(); ++x) {
            int sx = x - target.x;
            if (stretch) sx = sx * img.width / max(target.w, 1);
            else if (tile) sx %= img.width;
            int idx = sy * img.width + sx;
            if (img.format == PixelFormat::RGB565) {
                uint16_t p = static_cast<const uint16_t *>(img.pixels)[idx];
                if (op >= 255) row[x] = p;
                else {
                    Color c = fromRgb565(p);
                    blendPixel(row + x, c.red(), c.green(), c.blue(), op);
                }
            } else {
                uint32_t p = static_cast<const uint32_t *>(img.pixels)[idx];
                int a = int(p >> 24) * op / 255;
                blendPixel(row + x, int((p >> 16) & 0xff), int((p >> 8) & 0xff), int(p & 0xff), a);
            }
        }
    }
}

} // namespace mq
