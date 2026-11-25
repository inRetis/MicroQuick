// Window: owns the scene root, runs timers, layouts, computes dirty regions,
// repaints them into the framebuffer and dispatches pointer input.
//
// Porting MicroQuick to a new board only requires calling, from the main loop:
//   window.pointerEvent(...)   when the touch controller reports something
//   window.processFrame(now)   periodically (e.g. on each display vsync)
// and copying the returned dirty rectangles to the display.
#pragma once

#include "global.h"
#include "items.h"

namespace mq {

enum class PointerAction : uint8_t { Press, Move, Release };

class Window {
public:
    Window();

    static Window *instance();

    void setFramebuffer(uint16_t *pixels, int width, int height, int stridePixels = 0);
    void setRoot(Item *root);
    Item *root() const { return m_root; }
    int width() const { return m_width; }
    int height() const { return m_height; }
    Color color() const { return m_color; }
    void setColor(Color c) { m_color = c; requestUpdate(); }

    // Runs timers / layout / rendering. Returns the number of repainted
    // rectangles written to `dirty` (at most MQ_MAX_DIRTY_RECTS).
    int processFrame(uint32_t nowMs, Rect *dirty = nullptr);
    void pointerEvent(PointerAction action, int x, int y);

    uint32_t now() const { return m_now; }
    void invalidate(const Rect &r);      // repaint this area on the next frame
    void itemDestroyed(Item *item);
    void requestUpdate() { m_updateRequested = true; }
    bool updatePending() const { return m_updateRequested; }

    // Statistics (useful for profiling on target).
    uint32_t framesRendered() const { return m_frames; }
    uint32_t pixelsPainted() const { return m_pixelsPainted; }

private:
    void polishTree(Item *item);
    void collectDirty(Item *item, int ox, int oy, bool parentVisible, bool force, const Rect &clip);
    void addDirty(const Rect &r);
    void paintTree(class Painter &p, Item *item, int ox, int oy, real opacity);
    Item *hitTest(Item *item, int x, int y, int ox, int oy);

    Item *m_root = nullptr;
    uint16_t *m_pixels = nullptr;
    int m_width = 0, m_height = 0, m_stride = 0;
    Color m_color{0xff000000u};
    uint32_t m_now = 0;
    bool m_updateRequested = true;
    bool m_fullRepaint = true;

    Rect m_dirty[MQ_MAX_DIRTY_RECTS];
    int m_dirtyCount = 0;

    Rect m_extraDirty;
    Item *m_grabber = nullptr;
    int m_pressX = 0, m_pressY = 0;
    uint32_t m_frames = 0;
    uint32_t m_pixelsPainted = 0;
};

} // namespace mq
