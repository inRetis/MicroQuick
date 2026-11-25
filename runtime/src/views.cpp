#include "mq/views.h"
#include "mq/window.h"
#include <math.h>

namespace mq {

namespace {
constexpr int kDragThreshold = 6;          // pixels before a drag steals the touch
constexpr real kDeceleration = 0.0015f;    // pixels / ms^2 for kinetic scrolling
constexpr real kMinFlickVelocity = 0.05f;  // pixels / ms
} // namespace

// ================================================================ Flickable

Flickable::Flickable()
{
    contentX.setOwner(this, Geometry);
    contentY.setOwner(this, Geometry);
    contentWidth.setOwner(this, Geometry);
    contentHeight.setOwner(this, Geometry);
    contentItem.setParentItem(this);
}

int Flickable::maxContentX() const { return max(0, contentW() - width.value()); }
int Flickable::maxContentY() const { return max(0, contentH() - height.value()); }

bool Flickable::canFlickX() const
{
    if (!interactive.value()) return false;
    const int d = flickableDirection.value();
    if (d == AutoFlickDirection) return contentW() > width.value();
    return d == HorizontalFlick || d == HorizontalAndVerticalFlick;
}

bool Flickable::canFlickY() const
{
    if (!interactive.value()) return false;
    const int d = flickableDirection.value();
    if (d == AutoFlickDirection) return contentH() > height.value();
    return d == VerticalFlick || d == HorizontalAndVerticalFlick;
}

void Flickable::polish()
{
    if (!m_dragging && !isTicking()) {
        const int cx = clamp(contentX.value(), 0, maxContentX());
        const int cy = clamp(contentY.value(), 0, maxContentY());
        if (cx != contentX.value()) contentX.setValue(cx);
        if (cy != contentY.value()) contentY.setValue(cy);
    }
    contentItem.x.setValue(-contentX.value());
    contentItem.y.setValue(-contentY.value());
    contentItem.width.setValue(contentW());
    contentItem.height.setValue(contentH());
}

bool Flickable::filterDrag(int dx, int dy)
{
    const int ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy;
    if (canFlickY() && ay > kDragThreshold && ay >= ax) return true;
    if (canFlickX() && ax > kDragThreshold && ax >= ay) return true;
    return false;
}

void Flickable::cancelFlick()
{
    stopTicking();
    m_ax.velocity = m_ay.velocity = 0;
}

void Flickable::pointerPress(int lx, int ly)
{
    cancelFlick();
    m_ax.pressPos = m_ax.lastPos = lx;
    m_ay.pressPos = m_ay.lastPos = ly;
    m_ax.pressOffset = contentX.value();
    m_ay.pressOffset = contentY.value();
    m_lastTime = Window::instance()->now();
    m_dragging = true;
}

void Flickable::pointerMove(int lx, int ly)
{
    if (!m_dragging) return;
    const uint32_t now = Window::instance()->now();
    const uint32_t dt = now - m_lastTime;
    auto update = [dt](Axis &a, int pos, int maxOff, Property<int> &offset) {
        offset.setValue(clamp(a.pressOffset - (pos - a.pressPos), 0, maxOff));
        if (dt > 0) {
            const real instant = -real(pos - a.lastPos) / real(dt);
            a.velocity = 0.6f * instant + 0.4f * a.velocity;
            a.lastPos = pos;
        }
    };
    if (canFlickX()) update(m_ax, lx, maxContentX(), contentX);
    if (canFlickY()) update(m_ay, ly, maxContentY(), contentY);
    if (dt > 0) m_lastTime = now;
    moving.setValue(true);
}

void Flickable::pointerRelease(int lx, int ly, bool)
{
    pointerMove(lx, ly);
    m_dragging = false;
    const uint32_t now = Window::instance()->now();
    if (now - m_lastTime > 100) m_ax.velocity = m_ay.velocity = 0;   // finger stopped before lifting
    if (!canFlickX()) m_ax.velocity = 0;
    if (!canFlickY()) m_ay.velocity = 0;
    if (fabsf(m_ax.velocity) > kMinFlickVelocity || fabsf(m_ay.velocity) > kMinFlickVelocity) {
        m_ax.flickPos = real(contentX.value());
        m_ay.flickPos = real(contentY.value());
        m_flickTime = now;
        startTicking();
    } else {
        moving.setValue(false);
        Window::instance()->requestUpdate();
    }
}

void Flickable::pointerCancel()
{
    m_dragging = false;
    moving.setValue(false);
}

void Flickable::tick(uint32_t now)
{
    const real dt = real(now - m_flickTime);
    m_flickTime = now;
    auto step = [dt](Axis &a, real maxOff, Property<int> &offset) {
        if (a.velocity == 0) return;
        a.flickPos += a.velocity * dt;
        const real dv = kDeceleration * dt;
        if (fabsf(a.velocity) <= dv) a.velocity = 0;
        else a.velocity -= a.velocity > 0 ? dv : -dv;
        if (a.flickPos <= 0 || a.flickPos >= maxOff) {
            a.flickPos = clamp(a.flickPos, 0.0f, maxOff);
            a.velocity = 0;
        }
        offset.setValue(int(floorf(a.flickPos + 0.5f)));
    };
    step(m_ax, real(maxContentX()), contentX);
    step(m_ay, real(maxContentY()), contentY);
    if (m_ax.velocity == 0 && m_ay.velocity == 0) {
        stopTicking();
        moving.setValue(false);
    }
}

// ================================================================= ItemView

ItemView::ItemView()
{
    count.setOwner(this, Geometry);
    spacing.setOwner(this, Geometry);
    currentIndex.setOwner(this, Geometry);
}

void ItemView::componentComplete()
{
    Flickable::componentComplete();
    m_hlX.componentComplete();
    m_hlY.componentComplete();
    m_hlW.componentComplete();
    m_hlH.componentComplete();
    m_completed = true;
}

void ItemView::propertyChanged(PropertyBase *property, uint8_t flags)
{
    Flickable::propertyChanged(property, flags);
    if (property == &count) {
        for (int i = 0; i < m_capacity; ++i)
            if (m_slotRows[i] >= count.value()) m_slotRows[i] = -1;
        if (currentIndex.value() >= count.value() && count.value() > 0)
            currentIndex.setValue(count.value() - 1);
    }
}

void ItemView::setDelegates(Item *const *slots, int *slotRows, int capacity, void *ctx, BindFn bind)
{
    m_slots = slots;
    m_slotRows = slotRows;
    m_capacity = capacity;
    m_ctx = ctx;
    m_bind = bind;
    for (int i = 0; i < capacity; ++i) {
        slots[i]->setParentItem(&contentItem);
        slots[i]->visible.setValue(false);
        slotRows[i] = -1;
    }
    Window::instance()->requestUpdate();
}

void ItemView::setHighlight(Item *highlight)
{
    m_highlight = highlight;
    highlight->setParentItem(&contentItem);   // added first: drawn below the delegates
    m_hlX.setTarget(&highlight->x);
    m_hlY.setTarget(&highlight->y);
    m_hlW.setTarget(&highlight->width);
    m_hlH.setTarget(&highlight->height);
}

void ItemView::setHeader(Item *header)
{
    m_header = header;
    header->setParentItem(&contentItem);
}

void ItemView::setFooter(Item *footer)
{
    m_footer = footer;
    footer->setParentItem(&contentItem);
}

void ItemView::modelReset()
{
    for (int i = 0; i < m_capacity; ++i) m_slotRows[i] = -1;
    Window::instance()->requestUpdate();
}

void ItemView::incrementCurrentIndex()
{
    const int n = count.value();
    if (n <= 0) return;
    int i = currentIndex.value() + 1;
    if (i >= n) i = keyNavigationWraps.value() ? 0 : n - 1;
    currentIndex.set(i);
}

void ItemView::decrementCurrentIndex()
{
    const int n = count.value();
    if (n <= 0) return;
    int i = currentIndex.value() - 1;
    if (i < 0) i = keyNavigationWraps.value() ? n - 1 : 0;
    currentIndex.set(i);
}

void ItemView::hideUnused(int first, int last)
{
    for (int s = 0; s < m_capacity; ++s) {
        const int r = m_slotRows[s];
        if (r < 0 || r < first || r > last || r >= count.value()) {
            m_slotRows[s] = -1;
            m_slots[s]->visible.setValue(false);
        }
    }
}

Item *ItemView::showRow(int row)
{
    const int s = row % m_capacity;
    Item *d = m_slots[s];
    if (m_slotRows[s] != row) {
        m_bind(m_ctx, d, row);
        m_slotRows[s] = row;
    }
    d->visible.setValue(true);
    return d;
}

void ItemView::moveHighlight(int x, int y, int w, int h)
{
    if (!m_highlight || !highlightFollowsCurrentItem.value()) return;
    Item *hl = m_highlight;
    hl->visible.setValue(true);
    const int d = highlightMoveDuration.value();
    if (!m_hlPlaced || d <= 0 || !m_completed) {
        hl->x.setValue(x);
        hl->y.setValue(y);
        hl->width.setValue(w);
        hl->height.setValue(h);
        m_hlPlaced = true;
        return;
    }
    NumberAnimation *anims[] = {&m_hlX, &m_hlY, &m_hlW, &m_hlH};
    Property<int> *props[] = {&hl->x, &hl->y, &hl->width, &hl->height};
    const int targets[] = {x, y, w, h};
    for (int i = 0; i < 4; ++i) {
        NumberAnimation *a = anims[i];
        const bool moving = a->running.value();
        const int goal = moving ? int(a->to.value()) : props[i]->value();
        if (goal == targets[i]) continue;
        a->duration.setValue(d);
        a->easing_type.setValue(Easing::OutQuad);
        a->runBetween(real(props[i]->value()), real(targets[i]));
    }
}

int ItemView::headerSize(bool vertical) const
{
    if (!m_header || !m_header->visible.value()) return 0;
    return vertical ? m_header->height.value() : m_header->width.value();
}

int ItemView::footerSize(bool vertical) const
{
    if (!m_footer || !m_footer->visible.value()) return 0;
    return vertical ? m_footer->height.value() : m_footer->width.value();
}

// ================================================================= ListView

ListView::ListView()
{
    orientation.setOwner(this, Geometry);
}

void ListView::propertyChanged(PropertyBase *property, uint8_t flags)
{
    ItemView::propertyChanged(property, flags);
    if (property == &orientation) modelReset();
}

void ListView::modelReset()
{
    ItemView::modelReset();
    for (int i = 0; i < m_sizeCount; ++i) m_sizes[i] = -1;
    for (int i = 0; i < m_secCapacity; ++i) m_secRows[i] = -1;
}

void ListView::setSizeCache(int16_t *sizes, int n)
{
    m_sizes = sizes;
    m_sizeCount = n;
    for (int i = 0; i < n; ++i) sizes[i] = -1;
}

void ListView::setSections(Item *const *slots, int *slotRows, int capacity, void *ctx, SectionFn sectionOf,
                           SectionBindFn bind)
{
    m_secSlots = slots;
    m_secRows = slotRows;
    m_secCapacity = capacity;
    m_secCtx = ctx;
    m_sectionOf = sectionOf;
    m_secBind = bind;
    for (int i = 0; i < capacity; ++i) {
        slots[i]->setParentItem(&contentItem);
        slots[i]->visible.setValue(false);
        slotRows[i] = -1;
    }
}

int ListView::sizeOf(int row) const
{
    if (row < m_sizeCount && m_sizes[row] >= 0) return m_sizes[row];
    if (!m_capacity) return 0;
    return vertical() ? m_slots[0]->height.value() : m_slots[0]->width.value();   // estimate
}

void ListView::storeSize(int row, int size)
{
    if (row >= m_sizeCount || m_sizes[row] == size) return;
    m_sizes[row] = int16_t(size);
    Window::instance()->requestUpdate();   // positions after this row moved: lay out again
}

bool ListView::hasSection(int row) const
{
    if (!m_sectionOf || !m_secCapacity) return false;
    return row == 0 || !(m_sectionOf(m_secCtx, row) == m_sectionOf(m_secCtx, row - 1));
}

int ListView::sectionSize() const
{
    if (!m_secCapacity) return 0;
    return vertical() ? m_secSlots[0]->height.value() : m_secSlots[0]->width.value();
}

template <typename Fn>
int ListView::walk(Fn fn) const
{
    const int n = count.value();
    const int sec = sectionSize();
    int pos = headerSize(vertical());
    for (int r = 0; r < n; ++r) {
        const int secStart = pos;
        const int rowStart = pos + (hasSection(r) ? sec : 0);
        const int size = sizeOf(r);
        fn(r, secStart, rowStart, size);
        pos = rowStart + size + spacing.value();
    }
    if (n > 0) pos -= spacing.value();
    return pos + footerSize(vertical());
}

void ItemView::hideHighlightIfNoCurrent()
{
    if (m_highlight && (currentIndex.value() < 0 || currentIndex.value() >= count.value()))
        m_highlight->visible.setValue(false);
}

void ListView::polish()
{
    hideHighlightIfNoCurrent();
    const bool v = vertical();
    const int content = walk([](int, int, int, int) {});
    contentWidth.setValue(v ? width.value() : content);
    contentHeight.setValue(v ? content : height.value());
    Flickable::polish();

    const int off = v ? contentY.value() : contentX.value();
    const int view = v ? height.value() : width.value();
    int first = -1, last = -1;
    walk([&](int r, int secStart, int rowStart, int size) {
        if (rowStart + size > off && secStart < off + view) {
            if (first < 0) first = r;
            last = r;
        }
    });
    if (first >= 0 && m_capacity && last - first + 1 > m_capacity) last = first + m_capacity - 1;
    hideUnused(first, last);
    for (int s = 0; s < m_secCapacity; ++s) {
        const int r = m_secRows[s];
        if (r < 0 || r < first || r > last) {
            m_secRows[s] = -1;
            m_secSlots[s]->visible.setValue(false);
        }
    }

    const int cur = currentIndex.value();
    walk([&](int r, int secStart, int rowStart, int size) {
        if (r >= first && r <= last && m_capacity) {
            Item *d = showRow(r);
            storeSize(r, v ? d->height.value() : d->width.value());
            d->x.setValue(v ? 0 : rowStart);
            d->y.setValue(v ? rowStart : 0);
            if (rowStart > secStart) {
                const int s = r % m_secCapacity;
                Item *h = m_secSlots[s];
                if (m_secRows[s] != r) {
                    m_secBind(m_secCtx, h, m_sectionOf(m_secCtx, r));
                    m_secRows[s] = r;
                }
                h->x.setValue(v ? 0 : secStart);
                h->y.setValue(v ? secStart : 0);
                h->visible.setValue(true);
            }
        }
        if (r == cur) {
            if (v) moveHighlight(0, rowStart, width.value(), size);
            else moveHighlight(rowStart, 0, size, height.value());
        }
    });
    if (m_header) {
        m_header->x.setValue(0);
        m_header->y.setValue(0);
    }
    if (m_footer) {
        const int pos = content - footerSize(v);
        m_footer->x.setValue(v ? 0 : pos);
        m_footer->y.setValue(v ? pos : 0);
    }
}

void ListView::positionViewAtIndex(int index)
{
    polish();
    int target = -1;
    walk([&](int r, int secStart, int, int) {
        if (r == index) target = secStart;
    });
    if (target < 0) return;
    cancelFlick();
    if (vertical()) contentY.set(clamp(target, 0, maxContentY()));
    else contentX.set(clamp(target, 0, maxContentX()));
}

// ================================================================= GridView

GridView::GridView()
{
    cellWidth.setOwner(this, Geometry);
    cellHeight.setOwner(this, Geometry);
    flow.setOwner(this, Geometry);
}

int GridView::lines() const
{
    if (flow.value() == FlowTopToBottom) return max(1, height.value() / max(cellHeight.value(), 1));
    return max(1, width.value() / max(cellWidth.value(), 1));
}

void GridView::polish()
{
    hideHighlightIfNoCurrent();
    const bool v = flow.value() != FlowTopToBottom;   // scrolls vertically
    const int n = count.value();
    const int L = lines();
    const int along = v ? max(cellHeight.value(), 1) : max(cellWidth.value(), 1);
    const int hs = headerSize(v);
    const int lineCount = (n + L - 1) / L;
    const int content = hs + lineCount * along + footerSize(v);
    contentWidth.setValue(v ? width.value() : content);
    contentHeight.setValue(v ? content : height.value());
    Flickable::polish();

    const int off = v ? contentY.value() : contentX.value();
    const int view = v ? height.value() : width.value();
    const int firstLine = max(0, (off - hs) / along);
    const int lastLine = (off + view - 1 - hs) / along;
    int first = n > 0 ? firstLine * L : -1;
    int last = min(n - 1, (lastLine + 1) * L - 1);
    if (first >= n) first = last = -1;
    if (first >= 0 && m_capacity && last - first + 1 > m_capacity) last = first + m_capacity - 1;
    hideUnused(first, last);
    auto cellPos = [&](int i, int &x, int &y) {
        const int line = i / L, k = i % L;
        x = v ? k * cellWidth.value() : hs + line * cellWidth.value();
        y = v ? hs + line * cellHeight.value() : k * cellHeight.value();
    };
    if (first >= 0 && m_capacity) {
        for (int i = first; i <= last; ++i) {
            Item *d = showRow(i);
            int x, y;
            cellPos(i, x, y);
            d->x.setValue(x);
            d->y.setValue(y);
        }
    }
    const int cur = currentIndex.value();
    if (cur >= 0 && cur < n) {
        int x, y;
        cellPos(cur, x, y);
        moveHighlight(x, y, cellWidth.value(), cellHeight.value());
    }
    if (m_header) {
        m_header->x.setValue(0);
        m_header->y.setValue(0);
    }
    if (m_footer) {
        const int pos = content - footerSize(v);
        m_footer->x.setValue(v ? 0 : pos);
        m_footer->y.setValue(v ? pos : 0);
    }
}

void GridView::positionViewAtIndex(int index)
{
    polish();
    const bool v = flow.value() != FlowTopToBottom;
    const int along = v ? max(cellHeight.value(), 1) : max(cellWidth.value(), 1);
    const int pos = headerSize(v) + (index / lines()) * along;
    cancelFlick();
    if (v) contentY.set(clamp(pos, 0, maxContentY()));
    else contentX.set(clamp(pos, 0, maxContentX()));
}

// =================================================================== Loader

Loader::Loader() = default;

Loader::~Loader() { unload(); }

void Loader::attach(Item *root, void *object, DestroyFn destroy)
{
    unload();
    m_object = object;
    m_destroy = destroy;
    root->setParentItem(this);
    item.setValue(root);
    polish();
    status.setValue(1);
    sig_loaded.fire();
}

void Loader::unload()
{
    if (!m_object) return;
    void *obj = m_object;
    m_object = nullptr;
    item.setValue(nullptr);
    status.setValue(0);
    m_destroy(obj);
    implicitWidth.setValue(0);
    implicitHeight.setValue(0);
}

void Loader::polish()
{
    Item *it = item.value();
    if (!it) return;
    if (m_resize) {
        it->width.setValue(width.value());
        it->height.setValue(height.value());
    } else {
        implicitWidth.setValue(it->width.value());
        implicitHeight.setValue(it->height.value());
    }
}

} // namespace mq
