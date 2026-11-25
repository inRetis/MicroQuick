// QML-like visual types: Item, Rectangle, Text, Image, MouseArea, Row, Column,
// plus the non visual Timer.
#pragma once

#include "global.h"
#include "property.h"
#include "resources.h"

namespace mq {

class Painter;
class Window;

// Property flags used by Object::propertyChanged().
enum PropertyFlag : uint8_t {
    Paint = 1,         // repaint the item
    Geometry = 2,      // position/size changed
    Subtree = 4,       // repaint item and its children (opacity, visible, clip)
    Layout = 8,        // affects the parent's positioner
    Content = 16,      // item specific (text/font/image changed...)
    NonVisual = 32,    // item specific non visual (timer running...)
};

class Object {
public:
    Object() = default;
    Object(const Object &) = delete;
    Object &operator=(const Object &) = delete;
    virtual ~Object() = default;

    virtual void propertyChanged(PropertyBase *property, uint8_t flags) { (void)property; (void)flags; }
    // Called once the whole application tree is built (Component.onCompleted).
    virtual void componentComplete() {}
};

class Item : public Object {
public:
    Item();
    ~Item() override;   // detaches from the tree (used by Loader)

    Property<int> x, y, width, height;
    Property<int> implicitWidth, implicitHeight;
    Property<real> opacity{1.0f};
    Property<bool> visible{true};
    Property<bool> enabled{true};
    Property<bool> clip{false};
    Property<String> state;
    Property<Item *> parent{nullptr};

    void setParentItem(Item *parent);
    Item *parentItem() const { return parent.value(); }
    Item *firstChild() const { return m_firstChild; }
    Item *nextSibling() const { return m_nextSibling; }

    // Returns `item` or a static zero-sized item when null (bindings on
    // `parent` evaluated before the item is parented).
    static Item &orDummy(Item *item);

    // Maps item local coordinates to window coordinates (non tracking).
    void mapToScene(int &sx, int &sy) const;

    void update();          // schedule repaint
    void propertyChanged(PropertyBase *property, uint8_t flags) override;

    // Rendering hooks.
    virtual bool hasContent() const { return false; }
    // Area touched by paint() (defaults to the item rectangle).
    virtual Rect contentRect(int sceneX, int sceneY) const {
        return Rect(sceneX, sceneY, width.value(), height.value());
    }
    virtual void paint(Painter &painter, int sceneX, int sceneY, real opacity) {
        (void)painter; (void)sceneX; (void)sceneY; (void)opacity;
    }
    virtual void polish() {}                       // positioners
    virtual bool acceptsPointer() const { return false; }
    // Asked while a child holds the touch: return true to take it over (flick).
    virtual bool filterDrag(int dx, int dy) { (void)dx; (void)dy; return false; }
    virtual void pointerPress(int lx, int ly) { (void)lx; (void)ly; }
    virtual void pointerMove(int lx, int ly) { (void)lx; (void)ly; }
    virtual void pointerRelease(int lx, int ly, bool inside) { (void)lx; (void)ly; (void)inside; }
    virtual void pointerCancel() {}

private:
    friend class Window;
    Item *m_firstChild = nullptr;
    Item *m_lastChild = nullptr;
    Item *m_nextSibling = nullptr;
    Rect m_paintedRect;
    uint8_t m_dirty = 0;     // PropertyFlag bits pending repaint
};

class Rectangle : public Item {
public:
    Rectangle();
    Property<Color> color{Color(0xffffffffu)};
    Property<int> radius;
    Property<int> border_width;
    Property<Color> border_color{Color(0xff000000u)};

    bool hasContent() const override { return true; }
    void paint(Painter &painter, int sx, int sy, real opacity) override;
};

class Text : public Item {
public:
    enum HAlignment { AlignLeft = 1, AlignRight = 2, AlignHCenter = 4 };
    enum VAlignment { AlignTop = 32, AlignBottom = 64, AlignVCenter = 128 };
    enum WrapMode { NoWrap = 0, WordWrap = 1, WrapAnywhere = 3, Wrap = 4 };
    enum ElideMode { ElideLeft = 0, ElideRight = 1, ElideMiddle = 2, ElideNone = 3 };

    Text();
    Property<String> text;
    Property<Color> color{Color(0xff000000u)};
    Property<int> font_pixelSize{16};
    Property<int> horizontalAlignment{AlignLeft};
    Property<int> verticalAlignment{AlignTop};
    Property<int> wrapMode{NoWrap};
    Property<int> elide{ElideNone};
    Property<int> maximumLineCount{0x7fff};
    Property<int> lineCount{1};          // read only from QML

    bool hasContent() const override { return true; }
    Rect contentRect(int sceneX, int sceneY) const override;
    void paint(Painter &painter, int sx, int sy, real opacity) override;
    void propertyChanged(PropertyBase *property, uint8_t flags) override;

private:
    struct Layout;
    void updateImplicitSize();
    // Calls fn(begin, end, x, baselineOffset, elided) for each visible line.
    template <typename Fn> void layout(const FontData &font, Fn fn) const;
    int countLines(const FontData &font, int width) const;
};

class Image : public Item {
public:
    enum FillMode { Stretch = 0, Pad = 1, Tile = 2 };
    Image();
    Property<const ImageData *> source{nullptr};
    Property<int> fillMode{Stretch};

    bool hasContent() const override { return true; }
    void paint(Painter &painter, int sx, int sy, real opacity) override;
    void propertyChanged(PropertyBase *property, uint8_t flags) override;
};

class MouseArea : public Item {
public:
    MouseArea();
    Property<bool> pressed{false};     // read only from QML
    Property<int> mouseX, mouseY;      // read only from QML
    Signal<> sig_pressed;
    Signal<> sig_released;
    Signal<> sig_clicked;
    Signal<> sig_canceled;

    bool acceptsPointer() const override { return enabled.value(); }
    void pointerPress(int lx, int ly) override;
    void pointerMove(int lx, int ly) override;
    void pointerRelease(int lx, int ly, bool inside) override;
    void pointerCancel() override;
};

// Base for Row and Column.
class Positioner : public Item {
public:
    Property<int> spacing;
protected:
    Positioner();
};

class Row : public Positioner {
public:
    void polish() override;
};

class Column : public Positioner {
public:
    void polish() override;
};

class Timer : public Object {
public:
    Timer();
    ~Timer() override;
    Property<int> interval{1000};
    Property<bool> running{false};
    Property<bool> repeat{false};
    Property<bool> triggeredOnStart{false};
    Signal<> sig_triggered;

    void start() { running.set(true); }
    void stop() { running.set(false); }
    void restart() { running.set(false); running.set(true); }

    void propertyChanged(PropertyBase *property, uint8_t flags) override;
    void componentComplete() override;

    // Called by the window event loop; returns the next due time.
    void process(uint32_t nowMs);
    static Timer *first();
    Timer *next() const { return m_next; }

private:
    void arm();
    uint32_t m_due = 0;
    Timer *m_next = nullptr;
    bool m_completed = false;
};

} // namespace mq
