// QML states: State { name; PropertyChanges { target; prop: value } }.
#pragma once

#include "property.h"

namespace mq {

class PropertyChangeBase {
public:
    virtual void apply() = 0;
    virtual void revert() = 0;
protected:
    ~PropertyChangeBase() = default;
};

// Overrides `target` with a binding while the state is active and restores
// the previous value (or binding) when it is left.
template <typename T>
class PropertyChange : public PropertyChangeBase {
public:
    using Fn = T (*)(void *ctx);
    void init(Property<T> *target, void *ctx, Fn fn) { m_target = target; m_ctx = ctx; m_fn = fn; }

    void apply() override {
        m_savedBinding = m_target->binding();
        m_saved = m_target->value();
        m_binding.init(m_target, m_ctx, m_fn);   // detaches the saved binding
    }
    void revert() override {
        if (m_target->binding() == &m_binding) m_target->removeBinding();
        if (m_savedBinding) m_target->setBinding(m_savedBinding);
        else m_target->set(m_saved);
    }

private:
    Property<T> *m_target = nullptr;
    void *m_ctx = nullptr;
    Fn m_fn = nullptr;
    Binding<T> m_binding;
    BindingBase *m_savedBinding = nullptr;
    T m_saved{};
};

struct State {
    const char *name = "";
    PropertyChangeBase *const *changes = nullptr;
    int count = 0;
    Property<bool> *when = nullptr;   // optional 'when' condition
};

// One animated property of a Transition: remembers the value before the
// state change and animates from it to the value after the change.
class TransitionTrackBase {
public:
    virtual void capture() = 0;
    virtual void start() = 0;
protected:
    ~TransitionTrackBase() = default;
};

template <typename T, typename Anim>
class TransitionTrack : public TransitionTrackBase {
public:
    void init(Property<T> *property, Anim *animation) {
        m_property = property;
        m_anim = animation;
        animation->setTarget(property);
    }
    void capture() override { m_old = m_property->value(); }
    void start() override {
        const T now = m_property->value();
        if (now == m_old) return;
        m_property->writeValue(m_old);
        m_anim->runBetween(m_old, now);
    }

private:
    Property<T> *m_property = nullptr;
    Anim *m_anim = nullptr;
    T m_old{};
};

struct Transition {
    const char *from = "*";
    const char *to = "*";
    bool reversible = false;
    TransitionTrackBase *const *tracks = nullptr;
    int count = 0;
};

class StateGroup {
public:
    void init(Property<String> *stateProperty, const State *states, int count);
    void setTransitions(const Transition *transitions, int count);
    void setState(const String &name);
    // Re-evaluates the 'when' conditions (called when one of them changes).
    void evaluateWhen();
    static void whenChanged(void *group) { static_cast<StateGroup *>(group)->evaluateWhen(); }

private:
    static void onStateChanged(void *ctx);
    const Transition *findTransition(const char *from, const char *to) const;
    Property<String> *m_property = nullptr;
    const State *m_states = nullptr;
    int m_count = 0;
    int m_current = -1;
    const Transition *m_transitions = nullptr;
    int m_transitionCount = 0;
    int m_whenState = -1;      // state selected by a 'when' condition, if any
    ChangeHandler m_handler;
};

} // namespace mq
