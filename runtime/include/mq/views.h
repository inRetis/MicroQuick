// Scrollable and model/view types: Flickable, ListModel, Repeater, ListView,
// GridView.
//
// Delegates are generated C++ classes whose instances are preallocated by the
// generated code in fixed-size pools:
//  * Repeater: one delegate per possible row (static size or `capacity`);
//  * ListView / GridView: enough delegates to cover the viewport; they are
//    recycled (re-bound to another model row) while scrolling.
#pragma once

#include "animation.h"

namespace mq {

// ------------------------------------------------------------------ models

class ListModel : public Object {
public:
    Property<int> count;      // read only from QML
    Property<int> revision;   // bumped on every data change (views rebind)
    // Called by generated code after the rows changed.
    void changed(int newCount) { count.setValue(newCount); revision.setValue(revision.value() + 1); }
};

class Repeater : public Object {
public:
    Property<int> count;      // read only from QML
};

// --------------------------------------------------------------- Flickable

class Flickable : public Item, public Ticker {
public:
    enum FlickableDirection { AutoFlickDirection = 0, HorizontalFlick = 1, VerticalFlick = 2,
                              HorizontalAndVerticalFlick = 3 };
    Flickable();

    Property<int> contentX, contentY;
    Property<int> contentWidth{-1}, contentHeight{-1};   // -1: same as the view
    Property<int> flickableDirection{AutoFlickDirection};
    Property<bool> interactive{true};
    Property<bool> moving{false};                        // read only from QML
    Item contentItem;

    void polish() override;
    bool acceptsPointer() const override { return interactive.value(); }
    bool filterDrag(int dx, int dy) override;
    void pointerPress(int lx, int ly) override;
    void pointerMove(int lx, int ly) override;
    void pointerRelease(int lx, int ly, bool inside) override;
    void pointerCancel() override;
    void tick(uint32_t nowMs) override;

    int maxContentX() const;
    int maxContentY() const;
    void cancelFlick();

protected:
    virtual bool canFlickX() const;
    virtual bool canFlickY() const;
    int contentW() const { return contentWidth.value() < 0 ? width.value() : contentWidth.value(); }
    int contentH() const { return contentHeight.value() < 0 ? height.value() : contentHeight.value(); }
    bool dragging() const { return m_dragging; }

private:
    struct Axis {
        int pressPos = 0, pressOffset = 0, lastPos = 0;
        real velocity = 0, flickPos = 0;
    };
    Axis m_ax, m_ay;
    uint32_t m_lastTime = 0, m_flickTime = 0;
    bool m_dragging = false;
};

// ---------------------------------------------------------------- ItemView

// Common part of ListView and GridView: delegate pool, current item,
// highlight, header and footer.
class ItemView : public Flickable {
public:
    using BindFn = void (*)(void *ctx, Item *item, int index);

    Property<int> count;                       // number of model rows (set by generated code)
    Property<int> spacing;
    Property<int> currentIndex{0};
    Property<bool> highlightFollowsCurrentItem{true};
    Property<int> highlightMoveDuration{150};
    Property<bool> keyNavigationWraps{false};

    void setDelegates(Item *const *slots, int *slotRows, int capacity, void *ctx, BindFn bind);
    void setHighlight(Item *highlight);
    void setHeader(Item *header);
    void setFooter(Item *footer);
    // The model data changed: every visible delegate is bound again.
    virtual void modelReset();

    void incrementCurrentIndex();
    void decrementCurrentIndex();
    virtual void positionViewAtIndex(int index) = 0;
    // QML positionViewAtIndex(index, mode): MicroQuick always aligns the start.
    void positionViewAt(int index, int mode = 0) { (void)mode; positionViewAtIndex(index); }
    void positionViewAtBeginning() { positionViewAtIndex(0); }
    void positionViewAtEnd() { positionViewAtIndex(count.value() - 1); }

    void propertyChanged(PropertyBase *property, uint8_t flags) override;
    void componentComplete() override;

protected:
    ItemView();
    void hideUnused(int first, int last);
    void hideHighlightIfNoCurrent();
    Item *showRow(int row);          // binds (if needed) the slot of `row` and returns it
    void moveHighlight(int x, int y, int w, int h);
    int headerSize(bool vertical) const;
    int footerSize(bool vertical) const;

    Item *const *m_slots = nullptr;
    int *m_slotRows = nullptr;
    int m_capacity = 0;
    void *m_ctx = nullptr;
    BindFn m_bind = nullptr;
    Item *m_highlight = nullptr;
    Item *m_header = nullptr;
    Item *m_footer = nullptr;

private:
    NumberAnimation m_hlX, m_hlY, m_hlW, m_hlH;
    bool m_hlPlaced = false;
    bool m_completed = false;
};

// ---------------------------------------------------------------- ListView

class ListView : public ItemView {
public:
    enum Orientation { Horizontal = 1, Vertical = 2 };
    using SectionFn = String (*)(void *ctx, int index);
    using SectionBindFn = void (*)(void *ctx, Item *item, const String &section);

    ListView();
    Property<int> orientation{Vertical};
    Property<String> section_property;   // informative (sections are set up by generated code)

    // Delegates may have different sizes: their measured sizes are cached.
    void setSizeCache(int16_t *sizes, int count);
    void setSections(Item *const *slots, int *slotRows, int capacity, void *ctx, SectionFn sectionOf,
                     SectionBindFn bind);

    void positionViewAtIndex(int index) override;
    void polish() override;
    void propertyChanged(PropertyBase *property, uint8_t flags) override;
    void modelReset() override;

protected:
    bool canFlickX() const override { return interactive.value() && orientation.value() == Horizontal; }
    bool canFlickY() const override { return interactive.value() && orientation.value() != Horizontal; }

private:
    bool vertical() const { return orientation.value() != Horizontal; }
    int sizeOf(int row) const;
    void storeSize(int row, int size);
    bool hasSection(int row) const;
    int sectionSize() const;
    // Walks the rows; fn(row, sectionStart, rowStart, rowSize) returns false to stop.
    template <typename Fn> int walk(Fn fn) const;

    int16_t *m_sizes = nullptr;
    int m_sizeCount = 0;
    Item *const *m_secSlots = nullptr;
    int *m_secRows = nullptr;
    int m_secCapacity = 0;
    void *m_secCtx = nullptr;
    SectionFn m_sectionOf = nullptr;
    SectionBindFn m_secBind = nullptr;
};

// ---------------------------------------------------------------- GridView

class GridView : public ItemView {
public:
    enum Flow { FlowLeftToRight = 0, FlowTopToBottom = 1 };
    GridView();
    Property<int> cellWidth{100}, cellHeight{100};
    Property<int> flow{FlowLeftToRight};

    void positionViewAtIndex(int index) override;
    void polish() override;

protected:
    bool canFlickX() const override { return interactive.value() && flow.value() == FlowTopToBottom; }
    bool canFlickY() const override { return interactive.value() && flow.value() != FlowTopToBottom; }

private:
    int lines() const;     // number of cells across the non scrolling axis
};

// ------------------------------------------------------------------ Loader

// Instantiates one of several components known at compile time inside a
// static buffer (placement new): only one is alive at a time.
class Loader : public Item {
public:
    using DestroyFn = void (*)(void *object);
    Loader();
    ~Loader() override;

    Property<bool> active{true};
    Property<int> status{0};            // 0 = Null, 1 = Ready
    Property<Item *> item{nullptr};
    Signal<> sig_loaded;

    // Called by generated code after constructing `object` (whose root item
    // is `root`) in the loader's buffer.
    void attach(Item *root, void *object, DestroyFn destroy);
    void unload();
    void setResizeItem(bool on) { m_resize = on; }

    void polish() override;

private:
    void *m_object = nullptr;
    DestroyFn m_destroy = nullptr;
    bool m_resize = false;
};

} // namespace mq
