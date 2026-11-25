// Unit tests of the MicroQuick runtime (no generated code involved).
#include <mq/mq.h>
#include "check.h"
#include <cstring>
#include <new>

using namespace mq;

namespace {

struct Ctx {
    Property<int> a{1}, b{2};
    Property<String> label;
    int handlerCalls = 0;
};

int sumFn(void *c) { auto *x = static_cast<Ctx *>(c); return x->a.get() + x->b.get(); }
String labelFn(void *c) { auto *x = static_cast<Ctx *>(c); return String("a=") + x->a.get(); }
void onA(void *c) { static_cast<Ctx *>(c)->handlerCalls++; }

void testBindings()
{
    Ctx c;
    Property<int> sum;
    Binding<int> b;
    b.init(&sum, &c, &sumFn);
    CHECK_EQ(sum.value(), 3);
    c.a.set(10);
    CHECK_EQ(sum.value(), 12);
    c.b.set(5);
    CHECK_EQ(sum.value(), 15);

    // imperative assignment breaks the binding (QML semantics)
    sum.set(100);
    c.a.set(1);
    CHECK_EQ(sum.value(), 100);
    CHECK(!b.isAttached());

    Binding<String> lb;
    lb.init(&c.label, &c, &labelFn);
    CHECK(c.label.value() == "a=1");
    c.a.set(42);
    CHECK(c.label.value() == "a=42");
}

void testChangeHandler()
{
    Ctx c;
    ChangeHandler h;
    h.init(&c.a, &c, &onA);
    c.a.set(5);
    c.a.set(5);          // same value: no notification
    c.a.set(6);
    CHECK_EQ(c.handlerCalls, 2);
}

struct SigCtx { int total = 0; };
void slot(void *c, int v) { static_cast<SigCtx *>(c)->total += v; }

void testSignals()
{
    Signal<int> s;
    SigCtx c;
    Connection<int> c1, c2;
    c1.connect(s, &c, &slot);
    c2.connect(s, &c, &slot);
    s.fire(3);
    CHECK_EQ(c.total, 6);
    c2.disconnect();
    s.fire(1);
    CHECK_EQ(c.total, 7);
}

void testString()
{
    String s("Count: ");
    s = s + 42;
    CHECK(s == "Count: 42");
    CHECK(String::number(-7) == "-7");
    CHECK(String::number(0.5f) == "0.5");
    CHECK(String::number(3.0f) == "3");
    CHECK(String::number(2.346f, 2) == "2.35");
    CHECK(String("ñüé").charCount() == 3);    // UTF-8 code points, not bytes
    // truncation keeps valid UTF-8
    String big;
    for (int i = 0; i < 100; ++i) big += "é";
    CHECK(big.length() < MQ_STRING_CAPACITY);
    CHECK((big.length() % 2) == 0);
    CHECK_EQ(String("123").toInt(), 123);
}

void testPainter()
{
    static uint16_t fb[16 * 16];
    std::memset(fb, 0, sizeof fb);
    Painter p(fb, 16, 16, 16);
    p.fillRect(Rect(2, 2, 4, 4), Color(0xffff0000u));
    CHECK_EQ(fb[2 * 16 + 2], uint16_t(0xf800));
    CHECK_EQ(fb[1 * 16 + 1], uint16_t(0));
    p.setClip(Rect(0, 0, 3, 3));
    p.fillRect(Rect(0, 0, 16, 16), Color(0xff0000ffu));
    CHECK_EQ(fb[2 * 16 + 2], uint16_t(0x001f));
    CHECK_EQ(fb[2 * 16 + 3], uint16_t(0xf800));     // outside the clip: untouched
    // 50% white over black -> mid gray
    p.setClip(Rect(0, 0, 16, 16));
    p.fillRect(Rect(10, 10, 1, 1), Color(0xffffffffu), 0.5f);
    Color c = Painter::fromRgb565(fb[10 * 16 + 10]);
    CHECK(c.red() > 120 && c.red() < 136);
    // rounded rect: corner pixel stays empty, center filled
    std::memset(fb, 0, sizeof fb);
    p.fillRoundedRect(Rect(0, 0, 16, 16), 8, Color(0xffffffffu), 0, Color(), 1);
    CHECK_EQ(fb[0], uint16_t(0));
    CHECK_EQ(fb[8 * 16 + 8], uint16_t(0xffff));
}

void testWindowDirtyRegions()
{
    static uint16_t fb[64 * 64];
    Window *w = Window::instance();
    static Rectangle root;
    static Rectangle child;
    root.width.set(64);
    root.height.set(64);
    root.color.set(Color(0xff000000u));
    child.setParentItem(&root);
    child.x.set(4); child.y.set(4); child.width.set(8); child.height.set(8);
    child.color.set(Color(0xffffffffu));
    w->setFramebuffer(fb, 64, 64);
    w->setRoot(&root);
    Rect dirty[MQ_MAX_DIRTY_RECTS];
    int n = w->processFrame(0, dirty);
    CHECK_EQ(n, 1);
    CHECK(dirty[0] == Rect(0, 0, 64, 64));
    CHECK_EQ(fb[5 * 64 + 5], uint16_t(0xffff));
    CHECK_EQ(w->processFrame(16, dirty), 0);          // nothing changed: nothing repainted

    child.x.set(40);                                   // move: old + new position repainted
    n = w->processFrame(32, dirty);
    CHECK_EQ(n, 2);
    CHECK_EQ(fb[5 * 64 + 5], uint16_t(0));
    CHECK_EQ(fb[5 * 64 + 41], uint16_t(0xffff));
    uint32_t painted = w->pixelsPainted();
    child.color.set(Color(0xff00ff00u));
    w->processFrame(48, dirty);
    CHECK_EQ(w->pixelsPainted() - painted, 64u);       // only the 8x8 child
}

uint32_t g_now = 1000;
void frames(uint32_t ms)
{
    for (uint32_t t = 0; t < ms; t += 10) Window::instance()->processFrame(g_now += 10);
}

void testAnimations()
{
    static NumberAnimation a;
    static Rectangle box;
    a.setTarget(&box.x);
    a.to.set(100);
    a.duration.set(100);
    a.componentComplete();
    box.componentComplete();
    frames(10);   // animations start at the time of the last processed frame
    a.start();
    frames(50);
    CHECK(box.x.value() > 30 && box.x.value() < 70);
    frames(60);
    CHECK_EQ(box.x.value(), 100);
    CHECK(!a.running.value());

    // easing curves hit their end points
    for (int e = Easing::Linear; e <= Easing::OutElastic; ++e) {
        CHECK(Easing::apply(e, 0.0f) == 0.0f);
        CHECK(Easing::apply(e, 1.0f) > 0.999f && Easing::apply(e, 1.0f) < 1.001f);
    }

    // Behavior: writes (from bindings or imperative) are animated
    static Behavior<int, NumberAnimation> beh;
    static NumberAnimation ba;
    ba.duration.set(100);
    beh.install(&box.y, &ba);
    beh.componentComplete();
    ba.componentComplete();
    box.y.set(200);
    CHECK_EQ(box.y.value(), 0);           // not applied immediately
    frames(50);
    CHECK(box.y.value() > 50 && box.y.value() < 150);
    frames(60);
    CHECK_EQ(box.y.value(), 200);

    // SequentialAnimation: children run one after the other
    static NumberAnimation s1, s2;
    static SequentialAnimation seq;
    static Animation *kids[] = {&s1, &s2};
    s1.setTarget(&box.width); s1.to.set(50); s1.duration.set(100);
    s2.setTarget(&box.height); s2.to.set(80); s2.duration.set(100);
    seq.setChildren(kids, 2);
    seq.componentComplete();
    CHECK_EQ(seq.loopDuration(), 200);
    seq.start();
    frames(120);
    CHECK_EQ(box.width.value(), 50);
    CHECK(box.height.value() < 80);
    frames(100);
    CHECK_EQ(box.height.value(), 80);
}

struct Row : Rectangle { Property<int> index; };
int g_binds = 0;
void bindRow(void *, Item *item, int index) { static_cast<Row *>(item)->index.set(index); ++g_binds; }

void testListViewRecycling()
{
    static ListView view;
    static Row rows[4];
    static Item *slots[4] = {&rows[0], &rows[1], &rows[2], &rows[3]};
    static int slotRows[4];
    for (auto &r : rows) r.height.set(20);
    view.width.set(100);
    view.height.set(50);           // 3 rows visible (2.5)
    view.count.set(100);
    view.setDelegates(slots, slotRows, 4, nullptr, &bindRow);
    view.polish();
    CHECK_EQ(view.contentHeight.value(), 2000);
    CHECK_EQ(g_binds, 3);
    CHECK(rows[0].visible.value() && rows[2].visible.value() && !rows[3].visible.value());
    view.contentY.set(1000);       // jump to row 50
    view.polish();
    int visible = 0;
    for (auto &r : rows) {
        if (!r.visible.value()) continue;
        ++visible;
        CHECK(r.index.value() >= 50 && r.index.value() <= 52);
        CHECK_EQ(r.y.value(), r.index.value() * 20);
    }
    CHECK_EQ(visible, 3);
    view.contentY.set(5000);       // clamped to the end
    view.polish();
    CHECK_EQ(view.contentY.value(), 1950);
}

// ---- many dependencies: no fixed per-binding limit any more
Property<int> g_many[20];
int sumMany(void *) { int t = 0; for (auto &p : g_many) t += p.get(); return t; }

void testLinkPool()
{
    LinkPoolStats before = linkPoolStats();
    {
        Property<int> total;
        Binding<int> b;
        b.init(&total, nullptr, &sumMany);
        CHECK_EQ(linkPoolStats().used - before.used, 20);
        g_many[13].set(5);
        CHECK_EQ(total.value(), 5);
    }
    CHECK_EQ(linkPoolStats().used, before.used);   // links returned when the binding dies
}

void testLongLiteral()
{
    const char *lit = "A very long sentence that goes far beyond the capacity of a MicroQuick inline string buffer";
    String s = String::lit(lit);
    CHECK(s.c_str() == lit);                         // no copy
    CHECK(s == lit);
    String t = s + "!";                              // concatenation copies (bounded)
    CHECK(t.length() < MQ_STRING_CAPACITY);
}

void testFlickable()
{
    static Rectangle root;
    static Flickable f;
    static Rectangle content;
    root.width.set(200); root.height.set(200);
    f.setParentItem(&root);
    f.width.set(100); f.height.set(100);
    f.contentHeight.set(400);
    content.setParentItem(&f.contentItem);
    content.width.set(100); content.height.set(400);
    static uint16_t fb[200 * 200];
    Window *w = Window::instance();
    w->setFramebuffer(fb, 200, 200);
    w->setRoot(&root);
    frames(20);
    w->pointerEvent(PointerAction::Press, 50, 90);
    for (int i = 1; i <= 5; ++i) {
        frames(10);
        w->pointerEvent(PointerAction::Move, 50, 90 - i * 12);
    }
    w->pointerEvent(PointerAction::Release, 50, 30);
    CHECK(f.contentY.value() >= 50);
    frames(10);
    CHECK_EQ(f.contentItem.y.value(), -f.contentY.value());
    frames(2000);
    CHECK(f.contentY.value() <= 300);                // clamped to contentHeight - height
    CHECK(!f.moving.value());
}

struct Cell : Rectangle { Property<int> index; };
void bindCell(void *, Item *item, int index) { static_cast<Cell *>(item)->index.set(index); }

void testGridView()
{
    static GridView g;
    static Cell cells[12];
    static Item *slots[12];
    static int rows[12];
    for (int i = 0; i < 12; ++i) slots[i] = &cells[i];
    g.width.set(100); g.height.set(60);
    g.cellWidth.set(25); g.cellHeight.set(30);     // 4 columns, 2 visible rows
    g.count.set(10);
    g.setDelegates(slots, rows, 12, nullptr, &bindCell);
    g.polish();
    CHECK_EQ(g.contentHeight.value(), 90);          // 3 rows
    int visible = 0;
    for (auto &c : cells)
        if (c.visible.value()) {
            ++visible;
            CHECK_EQ(c.x.value(), (c.index.value() % 4) * 25);
            CHECK_EQ(c.y.value(), (c.index.value() / 4) * 30);
        }
    CHECK_EQ(visible, 8);
}

struct Line : Rectangle { Property<int> index; };
void bindLine(void *, Item *item, int index)
{
    auto *l = static_cast<Line *>(item);
    l->index.set(index);
    l->height.set(10 + index);                      // variable heights
}
String sectionOf(void *, int index) { return String::lit(index < 3 ? "A" : "B"); }
struct Header : Rectangle { Property<String> section; };
void bindHeader(void *, Item *item, const String &s) { static_cast<Header *>(item)->section.set(s); }

void testListViewVariableAndSections()
{
    static ListView v;
    static Line lines[8];
    static Item *slots[8];
    static int rows[8];
    static int16_t sizes[6];
    static Header headers[8];
    static Item *hslots[8];
    static int hrows[8];
    for (int i = 0; i < 8; ++i) { slots[i] = &lines[i]; hslots[i] = &headers[i]; headers[i].height.set(5); }
    v.width.set(50); v.height.set(500);
    v.count.set(6);
    v.setSizeCache(sizes, 6);
    v.setDelegates(slots, rows, 8, nullptr, &bindLine);
    v.setSections(hslots, hrows, 8, nullptr, &sectionOf, &bindHeader);
    for (int i = 0; i < 4; ++i) v.polish();         // sizes are learned while laying out
    // rows: A section header (5), rows 0..2 (10,11,12), B header (5), rows 3..5 (13,14,15)
    CHECK_EQ(v.contentHeight.value(), 5 + 10 + 11 + 12 + 5 + 13 + 14 + 15);
    for (auto &l : lines)
        if (l.visible.value() && l.index.value() == 3) CHECK_EQ(l.y.value(), 5 + 33 + 5);
    int headersShown = 0;
    for (auto &h : headers) headersShown += h.visible.value();
    CHECK_EQ(headersShown, 2);
}

struct Page : Rectangle {
    Property<int> mirror;
    Binding<int> b;
    static int fn(void *ctx) { return static_cast<Page *>(ctx)->width.get() * 2; }
    Page() { width.set(30); height.set(20); b.init(&mirror, this, &fn); }
};
static int g_destroyed = 0;

void testLoader()
{
    static Rectangle root;
    static Loader loader;
    alignas(Page) static unsigned char buf[sizeof(Page)];
    loader.setParentItem(&root);
    int linksBefore = linkPoolStats().used;
    auto *p = new (buf) Page();
    loader.attach(p, p, [](void *o) { static_cast<Page *>(o)->~Page(); ++g_destroyed; });
    CHECK(loader.item.value() == p);
    CHECK_EQ(loader.implicitWidth.value(), 30);
    CHECK_EQ(p->mirror.value(), 60);
    loader.unload();
    CHECK(loader.item.value() == nullptr);
    CHECK_EQ(g_destroyed, 1);
    CHECK_EQ(linkPoolStats().used, linksBefore);    // everything detached
    CHECK(root.firstChild() == &loader && loader.firstChild() == nullptr);
}

void testSpring()
{
    static Rectangle box;
    static SpringAnimation sp;
    static Behavior<int, SpringAnimation> beh;
    sp.spring.set(3); sp.damping.set(0.3f);
    beh.install(&box.x, &sp);
    beh.componentComplete();
    sp.componentComplete();
    frames(10);
    box.x.set(100);
    frames(100);
    CHECK(box.x.value() > 0 && box.x.value() != 100);
    frames(4000);
    CHECK_EQ(box.x.value(), 100);
    CHECK(!sp.running.value());
}

} // namespace

int main()
{
    testBindings();
    testChangeHandler();
    testSignals();
    testString();
    testPainter();
    testWindowDirtyRegions();
    testAnimations();
    testListViewRecycling();
    testLinkPool();
    testLongLiteral();
    testFlickable();
    testGridView();
    testListViewVariableAndSections();
    testLoader();
    testSpring();
    TEST_MAIN_END();
}
