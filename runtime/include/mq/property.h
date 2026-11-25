// Property / binding / signal system (the MicroQuick equivalent of Qt's
// Q_PROPERTY + QML bindings + signals & slots), without heap allocation.
//
//  * Property<T> stores a value and the list of observers depending on it.
//  * A Binding<T> evaluates a function (generated from a QML expression); every
//    Property read during evaluation is recorded as a dependency. When one of
//    them changes, the binding is queued and re-evaluated.
//  * ChangeHandler runs code when a property changes (onFooChanged).
//  * Signal<Args...> / Connection<Args...> implement QML signals and handlers.
//
// Updates are synchronous like in QML: a top-level Property::set() flushes the
// queue of dirty observers before returning.
#pragma once

#include "global.h"
#include "string.h"

namespace mq {

class PropertyBase;
class Observer;
class BindingBase;
class Object;

// A dependency edge: "observer depends on source". Edges are embedded in
// observers (fixed arrays) and chained in a doubly linked list per source.
struct Link {
    PropertyBase *source = nullptr;
    Observer *observer = nullptr;
    Link *next = nullptr;
    Link *prev = nullptr;
    Link *nextOwned = nullptr;   // chain of the links owned by one binding / free list
};

// Bindings take their dependency links from a shared static pool, so a
// binding may read any number of properties and only uses what it needs.
// The generated application registers a pool sized for it; a small default
// pool is used otherwise.
void registerLinkPool(Link *links, int count);
struct LinkPoolStats { int size; int used; int peak; };
LinkPoolStats linkPoolStats();

class Observer {
public:
    Observer() = default;
    Observer(const Observer &) = delete;
    Observer &operator=(const Observer &) = delete;
    virtual ~Observer();

    // Called (from the update queue) when a source changed.
    virtual void run() = 0;
    void markDirty();

    // Runs every queued observer until the queue is empty.
    static void flush();

protected:
    void unlinkFromPending();

private:
    friend class PropertyBase;
    Observer *m_nextPending = nullptr;
    bool m_queued = false;
};

class PropertyBase {
public:
    PropertyBase() = default;
    PropertyBase(const PropertyBase &) = delete;
    PropertyBase &operator=(const PropertyBase &) = delete;
    ~PropertyBase();

    // Owner notification: items use it to schedule repaints / relayouts.
    void setOwner(Object *owner, uint8_t flags) { m_owner = owner; m_flags = flags; }
    uint8_t flags() const { return m_flags; }

    void addLink(Link *link);
    static void removeLink(Link *link);

    // Records a read for the binding currently being evaluated, if any.
    void trackRead() const;
    // Marks observers dirty and flushes the queue when not already flushing.
    void notify();

    BindingBase *binding() const { return m_binding; }
    void setBinding(BindingBase *binding);   // attaches & evaluates
    void removeBinding();                    // detaches (QML: imperative assignment)

    // A Behavior is installed on this property: writes are routed to it.
    bool isIntercepted() const { return m_intercepted; }
    void setIntercepted(bool on) { m_intercepted = on; }

private:
    friend class BindingBase;
    Link *m_observers = nullptr;
    BindingBase *m_binding = nullptr;
    Object *m_owner = nullptr;
    uint8_t m_flags = 0;
    bool m_intercepted = false;
};

// Implemented by the animation module: lets a Behavior take over a write.
// Returns true when the write was consumed (an animation now runs).
bool interceptWrite(PropertyBase *property, const void *newValue);

template <typename T>
class Property : public PropertyBase {
public:
    Property() : m_value() {}
    explicit Property(const T &v) : m_value(v) {}

    // Read with dependency tracking (use in bindings / generated code).
    const T &get() const { trackRead(); return m_value; }
    // Read without tracking.
    const T &value() const { return m_value; }

    // Imperative assignment: removes any binding first (QML semantics).
    void set(const T &v) { removeBinding(); setValue(v); }
    // Writes the value keeping the binding (used by bindings themselves).
    // Goes through an installed Behavior, if any.
    void setValue(const T &v) {
        if (isIntercepted() && interceptWrite(this, &v)) return;
        writeValue(v);
    }
    // Raw write, bypassing Behaviors (used by animations).
    void writeValue(const T &v) {
        if (m_value == v) return;
        m_value = v;
        notify();
    }

private:
    T m_value;
};

class BindingBase : public Observer {
public:
    BindingBase() = default;
    ~BindingBase() override;

    void run() override;
    void evaluateNow() { run(); }
    void detach();             // drops dependencies; stops reacting
    bool isAttached() const { return m_attached; }

    void dependOn(const PropertyBase *source);
    static BindingBase *current();
    // Replaces the binding receiving dependency reads; returns the previous one.
    static BindingBase *swapCurrent(BindingBase *binding);

protected:
    virtual void evaluate() = 0;
    friend class PropertyBase;
    PropertyBase *m_target = nullptr;

private:
    void clearDeps();
    Link *m_deps = nullptr;
    bool m_attached = false;
    bool m_running = false;
};

template <typename T>
class Binding : public BindingBase {
public:
    using Fn = T (*)(void *ctx);
    Binding() = default;

    // Binds `target` to fn(ctx) and evaluates it immediately.
    void init(Property<T> *target, void *ctx, Fn fn) {
        m_target = target; m_ctx = ctx; m_fn = fn;
        target->setBinding(this);
    }

protected:
    void evaluate() override {
        T v = m_fn(m_ctx);      // reads are tracked
        swapCurrent(nullptr);   // the store itself must not be tracked
        static_cast<Property<T> *>(m_target)->setValue(v);
    }

private:
    void *m_ctx = nullptr;
    Fn m_fn = nullptr;
};

// Runs a callback whenever `source` changes (onXxxChanged handlers).
class ChangeHandler : public Observer {
public:
    using Fn = void (*)(void *ctx);
    void init(PropertyBase *source, void *ctx, Fn fn) {
        m_ctx = ctx; m_fn = fn;
        m_link.observer = this;
        source->addLink(&m_link);
    }
    void run() override { if (m_fn) m_fn(m_ctx); }
    ~ChangeHandler() override { PropertyBase::removeLink(&m_link); }

private:
    Link m_link;
    void *m_ctx = nullptr;
    Fn m_fn = nullptr;
};

// ---------------------------------------------------------------- signals

template <typename... Args> class Signal;

template <typename... Args>
class Connection {
public:
    using Fn = void (*)(void *ctx, Args...);
    Connection() = default;
    Connection(const Connection &) = delete;
    Connection &operator=(const Connection &) = delete;
    ~Connection() { disconnect(); }

    void connect(Signal<Args...> &signal, void *ctx, Fn fn) {
        disconnect();
        m_ctx = ctx; m_fn = fn; m_signal = &signal;
        // append to keep connection order (QML calls handlers in order)
        Connection **slot = &signal.m_first;
        while (*slot) slot = &(*slot)->m_next;
        *slot = this;
    }
    void disconnect() {
        if (!m_signal) return;
        Connection **slot = &m_signal->m_first;
        while (*slot && *slot != this) slot = &(*slot)->m_next;
        if (*slot) *slot = m_next;
        m_signal = nullptr; m_next = nullptr;
    }

private:
    friend class Signal<Args...>;
    Signal<Args...> *m_signal = nullptr;
    Connection *m_next = nullptr;
    void *m_ctx = nullptr;
    Fn m_fn = nullptr;
};

template <typename... Args>
class Signal {
public:
    Signal() = default;
    Signal(const Signal &) = delete;
    Signal &operator=(const Signal &) = delete;

    void fire(Args... args) {
        for (Connection<Args...> *c = m_first; c;) {
            Connection<Args...> *next = c->m_next;   // handler may disconnect itself
            c->m_fn(c->m_ctx, args...);
            c = next;
        }
        Observer::flush();
    }
    void operator()(Args... args) { fire(args...); }

private:
    friend class Connection<Args...>;
    Connection<Args...> *m_first = nullptr;
};

} // namespace mq
