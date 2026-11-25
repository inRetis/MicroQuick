#include "mq/window.h"
#include "mq/painter.h"
#include "mq/animation.h"

namespace mq {

Window::Window() = default;

Window *Window::instance()
{
    static Window window;
    return &window;
}

void Window::setFramebuffer(uint16_t *pixels, int width, int height, int stridePixels)
{
    m_pixels = pixels;
    m_width = width;
    m_height = height;
    m_stride = stridePixels > 0 ? stridePixels : width;
    m_fullRepaint = true;
    requestUpdate();
}

void Window::setRoot(Item *root)
{
    m_root = root;
    m_fullRepaint = true;
    requestUpdate();
}

void Window::invalidate(const Rect &r)
{
    m_extraDirty = m_extraDirty.united(r);
    requestUpdate();
}

void Window::itemDestroyed(Item *item)
{
    if (m_grabber == item) m_grabber = nullptr;
    if (m_root == item) m_root = nullptr;
    invalidate(item->m_paintedRect);
}

void Window::polishTree(Item *item)
{
    for (Item *c = item->m_firstChild; c; c = c->m_nextSibling) polishTree(c);
    item->polish();
}

void Window::addDirty(const Rect &rIn)
{
    Rect r = rIn.intersected(Rect(0, 0, m_width, m_height));
    if (r.isEmpty()) return;
    // merge with any overlapping rectangle (repeat: the union may overlap others)
    bool merged = true;
    while (merged) {
        merged = false;
        for (int i = 0; i < m_dirtyCount; ++i) {
            if (!m_dirty[i].intersects(r)) continue;
            r = r.united(m_dirty[i]);
            m_dirty[i] = m_dirty[--m_dirtyCount];
            merged = true;
            break;
        }
    }
    if (m_dirtyCount < MQ_MAX_DIRTY_RECTS) {
        m_dirty[m_dirtyCount++] = r;
        return;
    }
    // full: merge with the rectangle whose union grows the least
    int best = 0;
    long bestCost = -1;
    for (int i = 0; i < m_dirtyCount; ++i) {
        Rect u = m_dirty[i].united(r);
        long cost = long(u.w) * u.h - long(m_dirty[i].w) * m_dirty[i].h;
        if (bestCost < 0 || cost < bestCost) {
            bestCost = cost;
            best = i;
        }
    }
    Rect u = m_dirty[best].united(r);
    m_dirty[best] = m_dirty[--m_dirtyCount];
    addDirty(u);
}

void Window::collectDirty(Item *item, int ox, int oy, bool parentVisible, bool force, const Rect &clip)
{
    const bool vis = parentVisible && item->visible.value() && item->opacity.value() > 0.0f;
    const int ix = ox + item->x.value(), iy = oy + item->y.value();
    Rect r;
    if (vis && item->hasContent()) r = item->contentRect(ix, iy).intersected(clip);
    if (force || item->m_dirty || r != item->m_paintedRect) {
        addDirty(item->m_paintedRect);
        addDirty(r);
    }
    item->m_paintedRect = r;
    const bool childForce = force || (item->m_dirty & Subtree);
    item->m_dirty = 0;
    Rect childClip = clip;
    if (item->clip.value())
        childClip = clip.intersected(Rect(ix, iy, item->width.value(), item->height.value()));
    for (Item *c = item->m_firstChild; c; c = c->m_nextSibling)
        collectDirty(c, ix, iy, vis, childForce, childClip);
}

void Window::paintTree(Painter &p, Item *item, int ox, int oy, real opacity)
{
    if (!item->visible.value()) return;
    const real op = opacity * item->opacity.value();
    if (op <= 0.0f) return;
    const int ix = ox + item->x.value(), iy = oy + item->y.value();
    if (item->hasContent() && item->contentRect(ix, iy).intersects(p.clip()))
        item->paint(p, ix, iy, op);
    if (!item->m_firstChild) return;
    const Rect savedClip = p.clip();
    if (item->clip.value()) {
        Rect c = savedClip.intersected(Rect(ix, iy, item->width.value(), item->height.value()));
        if (c.isEmpty()) return;
        p.setClip(c);
    }
    for (Item *c = item->m_firstChild; c; c = c->m_nextSibling) paintTree(p, c, ix, iy, op);
    p.setClip(savedClip);
}

int Window::processFrame(uint32_t nowMs, Rect *dirtyOut)
{
    m_now = nowMs;
    for (Timer *t = Timer::first(); t; t = t->next()) t->process(nowMs);
    Ticker::tickAll(nowMs);
    if (!m_root || !m_pixels) return 0;
    if (!m_updateRequested && !m_fullRepaint) return 0;

    // Layout: positioners may change geometry which may in turn trigger
    // bindings; iterate until stable.
    for (int i = 0; i < 4; ++i) {
        m_updateRequested = false;
        polishTree(m_root);
        Observer::flush();
        if (!m_updateRequested) break;
    }
    m_updateRequested = false;

    m_dirtyCount = 0;
    const Rect screen(0, 0, m_width, m_height);
    if (m_fullRepaint) addDirty(screen);
    addDirty(m_extraDirty);
    m_extraDirty = Rect();
    collectDirty(m_root, 0, 0, true, m_fullRepaint, screen);
    m_fullRepaint = false;
    if (m_dirtyCount == 0) return 0;

    Painter painter(m_pixels, m_width, m_height, m_stride);
    for (int i = 0; i < m_dirtyCount; ++i) {
        painter.setClip(m_dirty[i]);
        painter.fillRect(m_dirty[i], m_color);
        paintTree(painter, m_root, 0, 0, 1.0f);
        m_pixelsPainted += uint32_t(m_dirty[i].w * m_dirty[i].h);
        if (dirtyOut) dirtyOut[i] = m_dirty[i];
    }
    ++m_frames;
    return m_dirtyCount;
}

// ------------------------------------------------------------------ input

static Item *hitChildren(Item *c, int x, int y, int ox, int oy,
                         Item *(*test)(Item *, int, int, int, int))
{
    if (!c) return nullptr;
    if (Item *r = hitChildren(c->nextSibling(), x, y, ox, oy, test)) return r;   // topmost first
    return test(c, x, y, ox, oy);
}

static Item *hitItem(Item *item, int x, int y, int ox, int oy)
{
    if (!item->visible.value() || !item->enabled.value()) return nullptr;
    const int ix = ox + item->x.value(), iy = oy + item->y.value();
    const Rect r(ix, iy, item->width.value(), item->height.value());
    if (item->clip.value() && !r.contains(x, y)) return nullptr;
    if (Item *hit = hitChildren(item->firstChild(), x, y, ix, iy, &hitItem)) return hit;
    if (item->acceptsPointer() && r.contains(x, y)) return item;
    return nullptr;
}

Item *Window::hitTest(Item *item, int x, int y, int ox, int oy)
{
    return hitItem(item, x, y, ox, oy);
}

void Window::pointerEvent(PointerAction action, int x, int y)
{
    if (!m_root) return;
    if (action == PointerAction::Press) {
        if (m_grabber) m_grabber->pointerCancel();
        m_pressX = x;
        m_pressY = y;
        m_grabber = hitTest(m_root, x, y, 0, 0);
        if (!m_grabber) return;
        int sx, sy;
        m_grabber->mapToScene(sx, sy);
        m_grabber->pointerPress(x - sx, y - sy);
        return;
    }
    if (!m_grabber) return;
    if (action == PointerAction::Move) {
        // a flickable ancestor may steal the touch from e.g. a MouseArea
        for (Item *a = m_grabber->parentItem(); a; a = a->parentItem()) {
            if (!a->filterDrag(x - m_pressX, y - m_pressY)) continue;
            m_grabber->pointerCancel();
            m_grabber = a;
            int ax, ay;
            a->mapToScene(ax, ay);
            a->pointerPress(m_pressX - ax, m_pressY - ay);
            break;
        }
    }
    int sx, sy;
    m_grabber->mapToScene(sx, sy);
    const int lx = x - sx, ly = y - sy;
    if (action == PointerAction::Move) {
        m_grabber->pointerMove(lx, ly);
    } else {
        Item *g = m_grabber;
        m_grabber = nullptr;
        const bool inside = lx >= 0 && ly >= 0 && lx < g->width.value() && ly < g->height.value();
        g->pointerRelease(lx, ly, inside);
    }
}

} // namespace mq
