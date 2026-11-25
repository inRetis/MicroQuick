#include "mq/items.h"
#include "mq/painter.h"
#include "mq/window.h"

namespace mq {

// ===================================================================== Item

Item::Item()
{
    x.setOwner(this, Geometry);
    y.setOwner(this, Geometry);
    width.setOwner(this, Geometry);
    height.setOwner(this, Geometry);
    opacity.setOwner(this, Subtree);
    visible.setOwner(this, Subtree);
    clip.setOwner(this, Subtree);
}

Item::~Item()
{
    Window *w = Window::instance();
    w->itemDestroyed(this);
    for (Item *c = m_firstChild; c; c = c->m_nextSibling) c->parent.writeValue(nullptr);
    m_firstChild = m_lastChild = nullptr;
    if (parent.value()) setParentItem(nullptr);
}

Item &Item::orDummy(Item *item)
{
    static Item dummy;
    return item ? *item : dummy;
}

void Item::setParentItem(Item *newParent)
{
    Item *old = parent.value();
    if (old == newParent) return;
    if (old) {
        Item *prev = nullptr;
        for (Item *c = old->m_firstChild; c; prev = c, c = c->m_nextSibling) {
            if (c != this) continue;
            if (prev) prev->m_nextSibling = m_nextSibling;
            else old->m_firstChild = m_nextSibling;
            if (old->m_lastChild == this) old->m_lastChild = prev;
            break;
        }
        m_nextSibling = nullptr;
        old->m_dirty |= Subtree;   // repaint where we were
    }
    if (newParent) {
        if (newParent->m_lastChild) newParent->m_lastChild->m_nextSibling = this;
        else newParent->m_firstChild = this;
        newParent->m_lastChild = this;
    }
    m_dirty |= Subtree;
    parent.set(newParent);
    Window::instance()->requestUpdate();
}

void Item::mapToScene(int &sx, int &sy) const
{
    sx = 0;
    sy = 0;
    for (const Item *i = this; i; i = i->parent.value()) {
        sx += i->x.value();
        sy += i->y.value();
    }
}

void Item::update()
{
    m_dirty |= Paint;
    Window::instance()->requestUpdate();
}

void Item::propertyChanged(PropertyBase *, uint8_t flags)
{
    if (flags & (Paint | Geometry | Subtree | Content)) {
        m_dirty |= flags;
        Window::instance()->requestUpdate();
    }
}

// ================================================================ Rectangle

Rectangle::Rectangle()
{
    color.setOwner(this, Paint);
    radius.setOwner(this, Paint);
    border_width.setOwner(this, Paint);
    border_color.setOwner(this, Paint);
}

void Rectangle::paint(Painter &p, int sx, int sy, real op)
{
    Rect r(sx, sy, width.value(), height.value());
    int bw = border_width.value();
    if (radius.value() <= 0 && bw <= 0)
        p.fillRect(r, color.value(), op);
    else
        p.fillRoundedRect(r, radius.value(), color.value(), bw, border_color.value(), op);
}

// ===================================================================== Text

namespace {

int glyphAdvance(const FontData &font, uint32_t cp)
{
    const Glyph *g = findGlyph(font, cp);
    return g ? g->advance : font.pixelSize / 3;
}

int lineWidth(const FontData &font, const char *s, const char *end)
{
    int w = 0;
    while (s < end) w += glyphAdvance(font, decodeUtf8(s));
    return w;
}

const char *skipSpaces(const char *p)
{
    while (*p == ' ') ++p;
    return p;
}

// Splits text into lines (explicit '\n' and wrapping when maxWidth > 0).
struct LineBreaker {
    const FontData &font;
    const char *p;
    int maxWidth;
    int mode;
    bool done = false;

    bool next(const char *&b, const char *&e)
    {
        if (done) return false;
        b = p;
        const char *q = p, *lastSpace = nullptr;
        int w = 0;
        while (*q && *q != '\n') {
            const char *cs = q;
            const uint32_t cp = decodeUtf8(q);
            const int adv = glyphAdvance(font, cp);
            if (maxWidth > 0 && mode != Text::NoWrap && w + adv > maxWidth && cs > b) {
                if (mode != Text::WrapAnywhere && lastSpace) {
                    e = lastSpace;
                    p = skipSpaces(lastSpace);
                    return true;
                }
                if (mode == Text::WordWrap) {
                    if (cp == ' ') {
                        e = cs;
                        p = skipSpaces(cs);
                        return true;
                    }
                } else {
                    e = cs;
                    p = cs;
                    return true;
                }
            }
            if (cp == ' ') lastSpace = cs;
            w += adv;
        }
        e = q;
        if (*q == '\n') p = q + 1;
        else done = true;
        return true;
    }
};

const char kEllipsis[] = "\xE2\x80\xA6";   // U+2026

// Draws (or measures when p == nullptr) text [b,e) elided to maxWidth.
int drawElided(Painter *p, int x, int baseline, const char *b, const char *e, int maxWidth,
               int mode, const FontData &font, Color c, real op)
{
    const bool haveEllipsis = findGlyph(font, 0x2026) != nullptr;
    const char *ell = haveEllipsis ? kEllipsis : "...";
    const int ellLen = haveEllipsis ? 3 : 3;
    const int ellW = lineWidth(font, ell, ell + ellLen);
    const int avail = maxWidth - ellW;
    const char *prefixEnd = b, *suffixBegin = e;
    if (mode == Text::ElideRight || mode == Text::ElideMiddle) {
        const int budget = mode == Text::ElideMiddle ? avail / 2 : avail;
        int w = 0;
        for (const char *q = b; q < e;) {
            const char *cs = q;
            w += glyphAdvance(font, decodeUtf8(q));
            if (w > budget) break;
            prefixEnd = q;
            (void)cs;
        }
    }
    if (mode == Text::ElideLeft || mode == Text::ElideMiddle) {
        const int used = lineWidth(font, b, prefixEnd);
        const int budget = mode == Text::ElideMiddle ? avail - used : avail;
        // walk back from the end over UTF-8 sequences
        int w = 0;
        const char *q = e;
        while (q > prefixEnd) {
            const char *start = q - 1;
            while (start > b && (uint8_t(*start) & 0xC0) == 0x80) --start;
            const char *tmp = start;
            w += glyphAdvance(font, decodeUtf8(tmp));
            if (w > budget) break;
            q = start;
        }
        suffixBegin = q;
    }
    if (mode == Text::ElideLeft) prefixEnd = b;
    if (mode == Text::ElideRight) suffixBegin = e;
    const int total = lineWidth(font, b, prefixEnd) + ellW + lineWidth(font, suffixBegin, e);
    if (p) {
        int cx = x;
        p->drawText(cx, baseline, b, int(prefixEnd - b), font, c, op);
        cx += lineWidth(font, b, prefixEnd);
        p->drawText(cx, baseline, ell, ellLen, font, c, op);
        cx += ellW;
        p->drawText(cx, baseline, suffixBegin, int(e - suffixBegin), font, c, op);
    }
    return total;
}

} // namespace

Text::Text()
{
    text.setOwner(this, Content);
    font_pixelSize.setOwner(this, Content);
    wrapMode.setOwner(this, Content);
    elide.setOwner(this, Content);
    maximumLineCount.setOwner(this, Content);
    color.setOwner(this, Paint);
    horizontalAlignment.setOwner(this, Paint);
    verticalAlignment.setOwner(this, Paint);
    updateImplicitSize();
}

void Text::propertyChanged(PropertyBase *property, uint8_t flags)
{
    Item::propertyChanged(property, flags);
    if (flags & Content) updateImplicitSize();
    else if (property == &width && wrapMode.value() != NoWrap) updateImplicitSize();
}

int Text::countLines(const FontData &font, int maxWidth) const
{
    LineBreaker br{font, text.value().c_str(), maxWidth, wrapMode.value()};
    const char *b, *e;
    int n = 0;
    while (br.next(b, e)) ++n;
    return n;
}

void Text::updateImplicitSize()
{
    const FontData *font = fontForPixelSize(font_pixelSize.value());
    if (!font) return;
    // implicitWidth: natural (unwrapped) width, like Qt Quick
    int w = 0;
    {
        LineBreaker br{*font, text.value().c_str(), 0, NoWrap};
        const char *b, *e;
        while (br.next(b, e)) w = max(w, lineWidth(*font, b, e));
    }
    const bool wraps = wrapMode.value() != NoWrap && width.value() > 0 && width.value() < w;
    int lines = countLines(*font, wraps ? width.value() : 0);
    lineCount.setValue(lines);
    lines = min(lines, max(maximumLineCount.value(), 1));
    implicitWidth.setValue(w);
    implicitHeight.setValue(lines * font->lineHeight);
}

template <typename Fn>
void Text::layout(const FontData &font, Fn fn) const
{
    const int w = width.value(), h = height.value();
    const int natural = implicitWidth.value();
    const bool wraps = wrapMode.value() != NoWrap && w > 0 && w < natural;
    const int maxLines = max(maximumLineCount.value(), 1);
    int lines = min(countLines(font, wraps ? w : 0), maxLines);
    const int textH = lines * font.lineHeight;
    const int va = verticalAlignment.value();
    int y = va == AlignVCenter ? (h - textH) / 2 : va == AlignBottom ? h - textH : 0;
    const int ha = horizontalAlignment.value();
    const int el = elide.value();

    LineBreaker br{font, text.value().c_str(), wraps ? w : 0, wrapMode.value()};
    const char *b, *e;
    int n = 0;
    while (br.next(b, e)) {
        ++n;
        const bool last = n == maxLines;
        const char *lineEndPtr = e;
        bool elided = false;
        if (last && !br.done && el != ElideNone) {
            // more text follows: the last line shows the rest of its paragraph, elided
            const char *pe = b;
            while (*pe && *pe != '\n') ++pe;
            lineEndPtr = pe;
            elided = true;
        }
        int lw = lineWidth(font, b, lineEndPtr);
        if (w > 0 && el != ElideNone && lw > w) elided = true;
        if (elided && w > 0) {
            const int mode = el == ElideNone ? ElideRight : el;
            lw = drawElided(nullptr, 0, 0, b, lineEndPtr, w, mode, font, Color(), 0);
        } else {
            elided = false;
        }
        const int x = ha == AlignHCenter ? (w - lw) / 2 : ha == AlignRight ? w - lw : 0;
        fn(b, lineEndPtr, x, y, lw, elided);
        y += font.lineHeight;
        if (last) break;
    }
}

Rect Text::contentRect(int sx, int sy) const
{
    Rect r(sx, sy, width.value(), height.value());
    const FontData *font = fontForPixelSize(font_pixelSize.value());
    if (!font) return r;
    layout(*font, [&](const char *, const char *, int x, int y, int lw, bool) {
        r = r.united(Rect(sx + x, sy + y, lw + font->pixelSize / 4, font->lineHeight));
    });
    return r;
}

void Text::paint(Painter &p, int sx, int sy, real op)
{
    const FontData *font = fontForPixelSize(font_pixelSize.value());
    if (!font) return;
    const int w = width.value();
    const int el = elide.value() == ElideNone ? ElideRight : elide.value();
    layout(*font, [&](const char *b, const char *e, int x, int y, int, bool elided) {
        const int baseline = sy + y + font->ascent;
        if (elided)
            drawElided(&p, sx + x, baseline, b, e, w, el, *font, color.value(), op);
        else
            p.drawText(sx + x, baseline, b, int(e - b), *font, color.value(), op);
    });
}

// ==================================================================== Image

Image::Image()
{
    source.setOwner(this, Content);
    fillMode.setOwner(this, Paint);
}

void Image::propertyChanged(PropertyBase *property, uint8_t flags)
{
    Item::propertyChanged(property, flags);
    if (flags & Content) {
        const ImageData *img = source.value();
        implicitWidth.setValue(img ? img->width : 0);
        implicitHeight.setValue(img ? img->height : 0);
    }
}

void Image::paint(Painter &p, int sx, int sy, real op)
{
    if (const ImageData *img = source.value())
        p.drawImage(Rect(sx, sy, width.value(), height.value()), *img, fillMode.value(), op);
}

// ================================================================ MouseArea

MouseArea::MouseArea() = default;

void MouseArea::pointerPress(int lx, int ly)
{
    mouseX.set(lx);
    mouseY.set(ly);
    pressed.set(true);
    sig_pressed.fire();
}

void MouseArea::pointerMove(int lx, int ly)
{
    mouseX.set(lx);
    mouseY.set(ly);
}

void MouseArea::pointerRelease(int lx, int ly, bool inside)
{
    mouseX.set(lx);
    mouseY.set(ly);
    pressed.set(false);
    sig_released.fire();
    if (inside) sig_clicked.fire();
}

void MouseArea::pointerCancel()
{
    pressed.set(false);
    sig_canceled.fire();
}

// =============================================================== Positioners

Positioner::Positioner() { spacing.setOwner(this, Geometry); }

void Row::polish()
{
    int pos = 0, h = 0, count = 0;
    for (Item *c = firstChild(); c; c = c->nextSibling()) {
        if (!c->visible.value()) continue;
        if (count++) pos += spacing.value();
        c->x.setValue(pos);
        pos += c->width.value();
        h = max(h, c->y.value() + c->height.value());
    }
    implicitWidth.setValue(pos);
    implicitHeight.setValue(h);
}

void Column::polish()
{
    int pos = 0, w = 0, count = 0;
    for (Item *c = firstChild(); c; c = c->nextSibling()) {
        if (!c->visible.value()) continue;
        if (count++) pos += spacing.value();
        c->y.setValue(pos);
        pos += c->height.value();
        w = max(w, c->x.value() + c->width.value());
    }
    implicitWidth.setValue(w);
    implicitHeight.setValue(pos);
}

// ==================================================================== Timer

namespace {
Timer *g_firstTimer = nullptr;
}

Timer::Timer()
{
    interval.setOwner(this, NonVisual);
    running.setOwner(this, NonVisual);
    m_next = g_firstTimer;
    g_firstTimer = this;
}

Timer::~Timer()
{
    for (Timer **t = &g_firstTimer; *t; t = &(*t)->m_next) {
        if (*t == this) {
            *t = m_next;
            break;
        }
    }
}

Timer *Timer::first() { return g_firstTimer; }

void Timer::propertyChanged(PropertyBase *, uint8_t)
{
    if (m_completed) arm();
}

void Timer::componentComplete()
{
    m_completed = true;
    arm();
}

void Timer::arm()
{
    if (!running.value()) return;
    uint32_t now = Window::instance()->now();
    m_due = triggeredOnStart.value() ? now : now + uint32_t(max(interval.value(), 1));
}

void Timer::process(uint32_t now)
{
    if (!m_completed || !running.value()) return;
    if (int32_t(now - m_due) < 0) return;
    if (repeat.value()) {
        m_due += uint32_t(max(interval.value(), 1));
        if (int32_t(now - m_due) >= 0) m_due = now + uint32_t(max(interval.value(), 1));
    } else {
        running.setValue(false);
    }
    sig_triggered.fire();
}

} // namespace mq
