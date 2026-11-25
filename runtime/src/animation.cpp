#include "mq/animation.h"
#include "mq/window.h"
#include <math.h>

namespace mq {

// =================================================================== Ticker

namespace {
Ticker *g_firstTicker = nullptr;
BehaviorBase *g_firstBehavior = nullptr;
} // namespace

Ticker::~Ticker() { stopTicking(); }

void Ticker::startTicking()
{
    if (m_ticking) return;
    m_ticking = true;
    m_nextTicker = g_firstTicker;
    g_firstTicker = this;
    Window::instance()->requestUpdate();
}

void Ticker::stopTicking()
{
    if (!m_ticking) return;
    for (Ticker **t = &g_firstTicker; *t; t = &(*t)->m_nextTicker) {
        if (*t == this) {
            *t = m_nextTicker;
            break;
        }
    }
    m_ticking = false;
    m_nextTicker = nullptr;
}

void Ticker::tickAll(uint32_t now)
{
    // A tick may stop (unlink) the current ticker or start others: fetch
    // the successor first; newly started tickers run on the next frame.
    for (Ticker *t = g_firstTicker; t;) {
        Ticker *next = t->m_nextTicker;
        t->tick(now);
        t = next;
    }
}

bool Ticker::anyTicking() { return g_firstTicker != nullptr; }

// =================================================================== Easing

real Easing::apply(int type, real p)
{
    p = clamp(p, 0.0f, 1.0f);
    switch (type) {
    case InQuad: return p * p;
    case OutQuad: return p * (2 - p);
    case InOutQuad: return p < 0.5f ? 2 * p * p : -1 + (4 - 2 * p) * p;
    case InCubic: return p * p * p;
    case OutCubic: { real q = p - 1; return q * q * q + 1; }
    case InOutCubic: return p < 0.5f ? 4 * p * p * p : (p - 1) * (2 * p - 2) * (2 * p - 2) + 1;
    case InSine: return 1 - cosf(p * 1.5707963f);
    case OutSine: return sinf(p * 1.5707963f);
    case InOutSine: return 0.5f * (1 - cosf(p * 3.1415927f));
    case OutBack: { const real s = 1.70158f; real q = p - 1; return q * q * ((s + 1) * q + s) + 1; }
    case OutBounce: {
        if (p < 1 / 2.75f) return 7.5625f * p * p;
        if (p < 2 / 2.75f) { p -= 1.5f / 2.75f; return 7.5625f * p * p + 0.75f; }
        if (p < 2.5f / 2.75f) { p -= 2.25f / 2.75f; return 7.5625f * p * p + 0.9375f; }
        p -= 2.625f / 2.75f;
        return 7.5625f * p * p + 0.984375f;
    }
    case OutElastic:
        if (p <= 0 || p >= 1) return p;
        return powf(2, -10 * p) * sinf((p - 0.075f) * (2 * 3.1415927f) / 0.3f) + 1;
    default: return p;
    }
}

// ================================================================ Animation

Animation::Animation()
{
    running.setOwner(this, NonVisual);
}

int Animation::totalDuration() const
{
    const int l = loops.value();
    if (l < 0) return -1;
    return loopDuration() * max(l, 1);
}

void Animation::applyTotal(int t)
{
    const int d = loopDuration();
    if (d <= 0) {
        apply(0);
        return;
    }
    const int total = totalDuration();
    if (total >= 0 && t >= total) apply(d);
    else apply(t % d);
}

void Animation::propertyChanged(PropertyBase *property, uint8_t)
{
    if (property != &running || !m_completed || m_group) return;
    if (running.value() && !m_active) startInternal();
    else if (!running.value() && m_active) stopInternal(false);
}

void Animation::componentComplete()
{
    m_completed = true;
    if (running.value() && !m_group && !m_active) startInternal();
}

void Animation::startInternal()
{
    m_active = true;
    m_startTime = Window::instance()->now();
    begin();
    applyTotal(0);
    startTicking();
    sig_started.fire();
}

void Animation::stopInternal(bool finished)
{
    m_active = false;
    stopTicking();
    sig_stopped.fire();
    if (finished) sig_finished.fire();
}

void Animation::restart()
{
    if (m_active) {
        m_startTime = Window::instance()->now();
        begin();
        applyTotal(0);
        return;
    }
    running.set(true);   // starts through propertyChanged once completed
}

void Animation::complete()
{
    if (!m_active) return;
    const int total = totalDuration();
    applyTotal(total >= 0 ? total : loopDuration());
    m_active = false;
    stopTicking();
    running.setValue(false);
    sig_stopped.fire();
    sig_finished.fire();
}

void Animation::tick(uint32_t now)
{
    if (!m_active) {
        stopTicking();
        return;
    }
    const int elapsed = int(now - m_startTime) - m_delay;
    if (elapsed < 0) return;   // still waiting for the start delay
    const int total = totalDuration();
    if (total >= 0 && elapsed >= total) {
        applyTotal(total);
        m_active = false;
        stopTicking();
        running.setValue(false);
        sig_stopped.fire();
        sig_finished.fire();
        return;
    }
    applyTotal(elapsed);
}

// ========================================================== NumberAnimation

NumberAnimation::NumberAnimation() = default;

real NumberAnimation::current() const
{
    if (m_int) return real(m_int->value());
    if (m_real) return m_real->value();
    return 0;
}

void NumberAnimation::runBetween(real a, real b)
{
    to.setValue(b);
    m_override = a;
    m_useOverride = true;
    restart();
}

void NumberAnimation::begin()
{
    m_start = m_useOverride ? m_override : (m_hasFrom ? from.value() : current());
    m_useOverride = false;
}

void NumberAnimation::apply(int t)
{
    const int d = duration.value();
    const real p = d > 0 ? real(t) / real(d) : 1.0f;
    const real v = m_start + (to.value() - m_start) * Easing::apply(easing_type.value(), p);
    if (m_int) m_int->writeValue(int(floorf(v + 0.5f)));
    else if (m_real) m_real->writeValue(v);
}

// =========================================================== ColorAnimation

ColorAnimation::ColorAnimation() = default;

void ColorAnimation::runBetween(Color a, Color b)
{
    to.setValue(b);
    m_override = a;
    m_useOverride = true;
    restart();
}

void ColorAnimation::begin()
{
    m_start = m_useOverride ? m_override : (m_hasFrom ? from.value() : (m_target ? m_target->value() : Color()));
    m_useOverride = false;
}

void ColorAnimation::apply(int t)
{
    if (!m_target) return;
    const int d = duration.value();
    const real e = Easing::apply(easing_type.value(), d > 0 ? real(t) / real(d) : 1.0f);
    const Color a = m_start, b = to.value();
    auto mix = [e](int x, int y) { return int(real(x) + real(y - x) * e + 0.5f); };
    m_target->writeValue(Color::rgba(mix(a.red(), b.red()), mix(a.green(), b.green()),
                                     mix(a.blue(), b.blue()), mix(a.alpha(), b.alpha())));
}

// ========================================================== SpringAnimation

SpringAnimation::SpringAnimation() { duration.setValue(-1); }

void SpringAnimation::write(real v)
{
    if (m_int) m_int->writeValue(int(floorf(v + 0.5f)));
    else if (m_real) m_real->writeValue(v);
}

void SpringAnimation::runBetween(real a, real b)
{
    to.setValue(b);
    if (!m_moving) {
        m_pos = a;
        m_vel = 0;
        m_moving = true;
        m_last = Window::instance()->now();
        running.setValue(true);
        startTicking();
    }
}

void SpringAnimation::tick(uint32_t now)
{
    if (!m_moving) {
        stopTicking();
        return;
    }
    int ms = int(now - m_last);
    m_last = now;
    const real target = to.value();
    const real k = spring.value(), d = damping.value(), m = max(mass.value(), 0.001f);
    const real vmax = velocity.value();
    // fixed sub-steps of 4 ms for stability; one time unit = 62.5 ms
    while (ms > 0) {
        const int step = min(ms, 4);
        ms -= step;
        const real dt = real(step) / 62.5f;
        if (k > 0) {
            const real acc = (k * (target - m_pos) - d * m_vel) / m;
            m_vel += acc * dt;
            if (vmax > 0) m_vel = clamp(m_vel, -vmax * 0.0625f, vmax * 0.0625f);
            m_pos += m_vel * dt;
        } else {
            const real maxStep = vmax > 0 ? vmax * real(step) / 1000.0f : 1e9f;
            const real diff = target - m_pos;
            m_pos += clamp(diff, -maxStep, maxStep);
            m_vel = 0;
        }
    }
    const real eps = max(epsilon.value(), 0.0001f);
    if (fabsf(target - m_pos) < eps && fabsf(m_vel) < eps * 10) {
        m_pos = target;
        m_moving = false;
        write(m_pos);
        stopTicking();
        running.setValue(false);
        sig_finished.fire();
        return;
    }
    write(m_pos);
}

// ======================================================== SmoothedAnimation

SmoothedAnimation::SmoothedAnimation() { duration.setValue(-1); }

void SmoothedAnimation::write(real v)
{
    if (m_int) m_int->writeValue(int(floorf(v + 0.5f)));
    else if (m_real) m_real->writeValue(v);
}

void SmoothedAnimation::runBetween(real a, real b)
{
    to.setValue(b);
    if (!m_moving) {
        m_pos = a;
        m_speed = 0;
        m_moving = true;
        m_last = Window::instance()->now();
        running.setValue(true);
        startTicking();
    }
}

void SmoothedAnimation::tick(uint32_t now)
{
    if (!m_moving) {
        stopTicking();
        return;
    }
    const real dt = real(int(now - m_last)) / 1000.0f;
    m_last = now;
    const real v = max(velocity.value(), 1.0f);
    const real diff = to.value() - m_pos;
    const real dist = fabsf(diff);
    // accelerate up to `velocity`, decelerate over the last quarter second
    const real wanted = min(v, dist / 0.25f + 1.0f);
    m_speed = min(wanted, m_speed + v * 4.0f * dt);
    const real step = m_speed * dt;
    if (step >= dist) {
        m_pos = to.value();
        m_moving = false;
        write(m_pos);
        stopTicking();
        running.setValue(false);
        sig_finished.fire();
        return;
    }
    m_pos += diff > 0 ? step : -step;
    write(m_pos);
}

// =================================================================== groups

void AnimationGroup::setChildren(Animation *const *children, int count)
{
    m_children = children;
    m_count = count;
    for (int i = 0; i < count; ++i) children[i]->setGroup(this);
}

static int childDuration(const Animation *a)
{
    const int t = a->totalDuration();
    return t < 0 ? a->loopDuration() : t;   // an infinite child runs one loop in a group
}

int SequentialAnimation::loopDuration() const
{
    int sum = 0;
    for (int i = 0; i < m_count; ++i) sum += childDuration(m_children[i]);
    return sum;
}

void SequentialAnimation::begin()
{
    m_current = -1;
    m_done = 0;
    m_lastT = 0;
}

void SequentialAnimation::apply(int t)
{
    if (t < m_lastT) begin();   // a new loop of the group
    m_lastT = t;
    int offset = 0;
    for (int i = 0; i < m_count; ++i) {
        Animation *c = m_children[i];
        const int d = childDuration(c);
        if (t < offset) break;
        const int local = t - offset;
        offset += d;
        if (i < m_done) continue;          // end value already applied
        if (i > m_current) {
            m_current = i;
            c->begin();
        }
        c->applyTotal(min(local, d));
        if (local >= d) m_done = i + 1;
    }
}

int ParallelAnimation::loopDuration() const
{
    int m = 0;
    for (int i = 0; i < m_count; ++i) m = max(m, childDuration(m_children[i]));
    return m;
}

void ParallelAnimation::begin()
{
    for (int i = 0; i < m_count; ++i) m_children[i]->begin();
}

void ParallelAnimation::apply(int t)
{
    for (int i = 0; i < m_count; ++i)
        m_children[i]->applyTotal(min(t, childDuration(m_children[i])));
}

// ================================================================= Behavior

BehaviorBase::BehaviorBase()
{
    m_next = g_firstBehavior;
    g_firstBehavior = this;
}

BehaviorBase::~BehaviorBase()
{
    for (BehaviorBase **b = &g_firstBehavior; *b; b = &(*b)->m_next) {
        if (*b == this) {
            *b = m_next;
            break;
        }
    }
    if (m_property) m_property->setIntercepted(false);
}

void BehaviorBase::installOn(PropertyBase *p)
{
    m_property = p;
    p->setIntercepted(true);
}

bool interceptWrite(PropertyBase *property, const void *newValue)
{
    for (BehaviorBase *b = g_firstBehavior; b; b = b->m_next)
        if (b->m_property == property) return b->intercept(newValue);
    return false;
}

} // namespace mq
