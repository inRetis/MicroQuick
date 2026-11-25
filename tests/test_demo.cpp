// End-to-end test of the demo: QML compiled to C++, run headless with a
// virtual clock, driven by synthetic touch events. Also checks that the
// runtime performs no dynamic allocation.
#include "mq_app.h"
#include "check.h"
#include <cstdlib>
#include <new>

static int g_allocations = 0;
void *operator new(std::size_t n) { ++g_allocations; return std::malloc(n ? n : 1); }
void *operator new[](std::size_t n) { ++g_allocations; return std::malloc(n ? n : 1); }
void operator delete(void *p) noexcept { std::free(p); }
void operator delete[](void *p) noexcept { std::free(p); }
void operator delete(void *p, std::size_t) noexcept { std::free(p); }
void operator delete[](void *p, std::size_t) noexcept { std::free(p); }

static uint16_t framebuffer[mq_app_width * mq_app_height];
static uint32_t now = 0;

static void run(uint32_t ms)
{
    for (uint32_t t = 0; t < ms; t += 10) mq::Window::instance()->processFrame(now += 10);
}

static void click(int x, int y)
{
    auto *w = mq::Window::instance();
    w->pointerEvent(mq::PointerAction::Press, x, y);
    run(20);
    w->pointerEvent(mq::PointerAction::Release, x, y);
    run(20);
}

static mq::Color pixel(int x, int y)
{
    return mq::Painter::fromRgb565(framebuffer[y * mq_app_width + x]);
}

static int centerX(mq::Item &item)
{
    int sx, sy;
    item.mapToScene(sx, sy);
    return sx + item.width.value() / 2;
}

static int centerY(mq::Item &item)
{
    int sx, sy;
    item.mapToScene(sx, sy);
    return sy + item.height.value() / 2;
}

int main()
{
    auto *root = static_cast<Main *>(mq_app_root());
    auto *win = mq::Window::instance();
    win->setFramebuffer(framebuffer, mq_app_width, mq_app_height);
    win->setRoot(root);
    run(100);

    CHECK_EQ(root->width.value(), 480);
    CHECK_EQ(root->count.value(), 0);
    // background color #1e2430 at a corner
    mq::Color bg = pixel(2, 268);
    CHECK(bg.red() >= 0x16 && bg.red() <= 0x26 && bg.blue() >= 0x28 && bg.blue() <= 0x38);  // RGB565 rounding

    // the "+" button (id: plus) increments the counter
    click(centerX(root->plus), centerY(root->plus));
    click(centerX(root->plus), centerY(root->plus));
    CHECK_EQ(root->count.value(), 2);

    // pressing darkens the button (binding on mouse.pressed)
    mq::Color before = pixel(centerX(root->plus) - 20, centerY(root->plus));
    win->pointerEvent(mq::PointerAction::Press, centerX(root->plus), centerY(root->plus));
    run(20);
    mq::Color pressed = pixel(centerX(root->plus) - 20, centerY(root->plus));
    CHECK(pressed.green() < before.green());
    // releasing outside cancels the click
    win->pointerEvent(mq::PointerAction::Release, 5, 5);
    run(20);
    CHECK_EQ(root->count.value(), 2);

    // Switch: state machine driven by `when: root.checked`
    CHECK(!root->turbo.checked.value());
    CHECK(root->turbo.state.value() == "");
    CHECK_EQ(root->turbo.knob.x.value(), 3);
    click(centerX(root->turbo), centerY(root->turbo));
    CHECK(root->turbo.checked.value());
    CHECK(root->turbo.state.value() == "on");
    // the knob slides (Behavior on x): in between after 60 ms, at the end after 300 ms
    run(20);
    CHECK(root->turbo.knob.x.value() > 3 && root->turbo.knob.x.value() < 27);
    run(300);
    CHECK_EQ(root->turbo.knob.x.value(), 27);
    click(centerX(root->turbo), centerY(root->turbo));
    CHECK(root->turbo.state.value() == "");
    run(300);
    CHECK_EQ(root->turbo.knob.x.value(), 3);   // value restored when leaving the state

    // Timers: one second of virtual time
    int secondsBefore = root->seconds.value();
    run(1000);
    CHECK_EQ(root->seconds.value(), secondsBefore + 1);
    CHECK(root->progress.value.value() > 0);

    // Tabs: the pages slide with an animation (Behavior on x, 350 ms)
    root->page.set(1);
    run(100);
    CHECK(root->pages.x.value() < 0 && root->pages.x.value() > -480);
    run(400);
    CHECK_EQ(root->pages.x.value(), -480);

    // ListView: 9 rows, pool of recycled delegates, selection by touch
    mq::ListView &list = root->sensors;
    CHECK_EQ(list.count.value(), 9);
    int lx, ly;
    list.mapToScene(lx, ly);
    click(lx + 50, ly + 36 + 16);          // second row
    CHECK(root->selName.value() == "Humidity");
    CHECK(root->selUnit.value() == "%");

    // drag up: the ListView steals the touch from the delegate's MouseArea
    win->pointerEvent(mq::PointerAction::Press, lx + 50, ly + 130);
    for (int i = 1; i <= 6; ++i) {
        run(10);
        win->pointerEvent(mq::PointerAction::Move, lx + 50, ly + 130 - i * 15);
    }
    win->pointerEvent(mq::PointerAction::Release, lx + 50, ly + 40);
    CHECK(root->selName.value() == "Humidity");     // no click delivered
    int afterDrag = list.contentY.value();
    CHECK(afterDrag >= 80);
    run(1500);                                       // kinetic scrolling continues
    CHECK(list.contentY.value() > afterDrag);
    CHECK_EQ(list.contentY.value(), list.contentHeight.value() - list.height.value());
    CHECK(!list.moving.value());
    // last row now visible and selectable
    click(lx + 50, ly + list.height.value() - 10);
    CHECK(root->selName.value() == "Flow");

    // Tasks page: mutable ListModel, sections, Loader
    root->page.set(2);
    run(800);
    CHECK_EQ(root->todoModel.count.value(), 4);
    CHECK_EQ(root->doneCount(), 2);
    root->addTask();
    run(100);
    CHECK_EQ(root->todoModel.count.value(), 5);
    CHECK_EQ(root->todoList.count.value(), 5);
    CHECK_EQ(root->todoList.currentIndex.value(), 4);

    // Idle frames repaint only what changes (the timers update two texts / the bar).
    uint32_t pixels = win->pixelsPainted();
    run(10);
    CHECK(win->pixelsPainted() - pixels < uint32_t(mq_app_width * mq_app_height / 3));

    CHECK_EQ(g_allocations, 0);
    TEST_MAIN_END();
}
