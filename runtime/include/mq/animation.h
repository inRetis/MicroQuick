// Animations: NumberAnimation, ColorAnimation, PauseAnimation,
// SequentialAnimation, ParallelAnimation and Behavior.
// All of them are driven by the Window frame loop through Ticker.
#pragma once

#include "items.h"

namespace mq {

// Something that needs a callback on every frame while active
// (running animations, kinetic scrolling...). Intrusive list, no heap.
class Ticker {
public:
    virtual ~Ticker();
    virtual void tick(uint32_t nowMs) = 0;
    void startTicking();
    void stopTicking();
    bool isTicking() const { return m_ticking; }
    static void tickAll(uint32_t nowMs);
    static bool anyTicking();

private:
    Ticker *m_nextTicker = nullptr;
    bool m_ticking = false;
};

namespace Easing {
enum Type {
    Linear = 0,
    InQuad, OutQuad, InOutQuad,
    InCubic, OutCubic, InOutCubic,
    InSine, OutSine, InOutSine,
    OutBack, OutBounce, OutElastic,
};
real apply(int type, real progress);
} // namespace Easing

class Animation : public Object, public Ticker {
public:
    enum { Infinite = -2 };

    Property<bool> running{false};
    Property<int> loops{1};
    Property<int> duration{250};
    Signal<> sig_started;
    Signal<> sig_stopped;
    Signal<> sig_finished;

    void start() { if (running.value()) restart(); else running.set(true); }
    void stop() { running.set(false); }
    void restart();
    void complete();   // jumps to the end

    void propertyChanged(PropertyBase *property, uint8_t flags) override;
    void componentComplete() override;
    void tick(uint32_t nowMs) override;

    // ---- engine interface (also used by groups to drive children)
    virtual int loopDuration() const { return duration.value(); }
    int totalDuration() const;            // -1 when infinite
    virtual void begin() {}               // capture start values
    virtual void apply(int t) = 0;        // t in [0, loopDuration()]
    void applyTotal(int t);               // handles loops
    void setGroup(Animation *group) { m_group = group; }
    void setStartDelay(int ms) { m_delay = ms; }   // used by Transition sequences

protected:
    Animation();

private:
    void startInternal();
    void stopInternal(bool finished);
    Animation *m_group = nullptr;
    uint32_t m_startTime = 0;
    int m_delay = 0;
    bool m_completed = false;
    bool m_active = false;
};

class NumberAnimation : public Animation {
public:
    NumberAnimation();
    Property<real> from;
    Property<real> to;
    Property<int> easing_type{Easing::Linear};

    void setTarget(Property<int> *target) { m_int = target; m_real = nullptr; }
    void setTarget(Property<real> *target) { m_real = target; m_int = nullptr; }
    void setHasFrom(bool on) { m_hasFrom = on; }
    // Used by Behavior: animates from `a` to `b` now.
    void runBetween(real a, real b);

    void begin() override;
    void apply(int t) override;

private:
    real current() const;
    Property<int> *m_int = nullptr;
    Property<real> *m_real = nullptr;
    real m_start = 0;
    real m_override = 0;
    bool m_hasFrom = false;
    bool m_useOverride = false;
};

class ColorAnimation : public Animation {
public:
    ColorAnimation();
    Property<Color> from;
    Property<Color> to;
    Property<int> easing_type{Easing::Linear};

    void setTarget(Property<Color> *target) { m_target = target; }
    void setHasFrom(bool on) { m_hasFrom = on; }
    void runBetween(Color a, Color b);

    void begin() override;
    void apply(int t) override;

private:
    Property<Color> *m_target = nullptr;
    Color m_start;
    Color m_override;
    bool m_hasFrom = false;
    bool m_useOverride = false;
};

// Physics based follower (Behavior on x { SpringAnimation { spring: 3; damping: 0.2 } }).
class SpringAnimation : public Animation {
public:
    SpringAnimation();
    Property<real> spring;          // stiffness; 0 = move at `velocity`
    Property<real> damping;
    Property<real> mass{1.0f};
    Property<real> epsilon{0.01f};
    Property<real> velocity;        // max speed in units/s (0 = unlimited)
    Property<real> to;

    void setTarget(Property<int> *t) { m_int = t; m_real = nullptr; }
    void setTarget(Property<real> *t) { m_real = t; m_int = nullptr; }
    void runBetween(real a, real b);
    void tick(uint32_t nowMs) override;
    void apply(int) override {}

private:
    void write(real v);
    Property<int> *m_int = nullptr;
    Property<real> *m_real = nullptr;
    real m_pos = 0, m_vel = 0;
    uint32_t m_last = 0;
    bool m_moving = false;
};

// Follows the target with a limited velocity and smooth deceleration.
class SmoothedAnimation : public Animation {
public:
    SmoothedAnimation();
    Property<real> velocity{200.0f};   // units/s
    Property<real> to;

    void setTarget(Property<int> *t) { m_int = t; m_real = nullptr; }
    void setTarget(Property<real> *t) { m_real = t; m_int = nullptr; }
    void runBetween(real a, real b);
    void tick(uint32_t nowMs) override;
    void apply(int) override {}

private:
    void write(real v);
    Property<int> *m_int = nullptr;
    Property<real> *m_real = nullptr;
    real m_pos = 0, m_speed = 0;
    uint32_t m_last = 0;
    bool m_moving = false;
};

class PauseAnimation : public Animation {
public:
    void apply(int) override {}
};

class AnimationGroup : public Animation {
public:
    void setChildren(Animation *const *children, int count);
protected:
    Animation *const *m_children = nullptr;
    int m_count = 0;
};

class SequentialAnimation : public AnimationGroup {
public:
    int loopDuration() const override;
    void begin() override;
    void apply(int t) override;
private:
    int m_current = -1;
    int m_done = 0;
    int m_lastT = 0;
};

class ParallelAnimation : public AnimationGroup {
public:
    int loopDuration() const override;
    void begin() override;
    void apply(int t) override;
};

// Behavior on <property> { NumberAnimation {...} }
class BehaviorBase : public Object {
public:
    Property<bool> enabled{true};
    void componentComplete() override { m_completed = true; }
    virtual bool intercept(const void *newValue) = 0;

protected:
    BehaviorBase();
    ~BehaviorBase() override;
    void installOn(PropertyBase *p);
    bool m_completed = false;

private:
    friend bool interceptWrite(PropertyBase *, const void *);
    PropertyBase *m_property = nullptr;
    BehaviorBase *m_next = nullptr;
};

template <typename T, typename Anim>
class Behavior : public BehaviorBase {
public:
    void install(Property<T> *property, Anim *animation) {
        m_target = property;
        m_anim = animation;
        animation->setTarget(property);
        installOn(property);
    }
    bool intercept(const void *v) override {
        if (!m_completed || !enabled.value() || !m_anim) return false;
        const T &next = *static_cast<const T *>(v);
        if (next == m_target->value() && !m_anim->running.value()) return true;
        m_anim->runBetween(m_target->value(), next);
        return true;
    }

private:
    Property<T> *m_target = nullptr;
    Anim *m_anim = nullptr;
};

} // namespace mq
