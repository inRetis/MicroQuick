#include "mq/property.h"
#include "mq/items.h"

namespace mq {

namespace {
Observer *g_pendingHead = nullptr;
Observer *g_pendingTail = nullptr;
bool g_flushing = false;
BindingBase *g_current = nullptr;
constexpr uint32_t kMaxFlushIterations = 100000;   // binding loop detection

Link g_defaultPool[MQ_DEFAULT_LINK_POOL];
Link *g_pool = g_defaultPool;
int g_poolSize = MQ_DEFAULT_LINK_POOL;
Link *g_freeLinks = nullptr;
int g_poolNext = 0;        // links never used yet: g_pool[g_poolNext..]
int g_linksUsed = 0;
int g_linksPeak = 0;

Link *allocLink()
{
    Link *l = g_freeLinks;
    if (l) {
        g_freeLinks = l->nextOwned;
    } else if (g_poolNext < g_poolSize) {
        l = &g_pool[g_poolNext++];
    } else {
        fatal("MicroQuick: dependency link pool exhausted (see mq::registerLinkPool)");
        return nullptr;
    }
    if (++g_linksUsed > g_linksPeak) g_linksPeak = g_linksUsed;
    *l = Link();
    return l;
}

void freeLink(Link *l)
{
    l->nextOwned = g_freeLinks;
    g_freeLinks = l;
    --g_linksUsed;
}
} // namespace

void registerLinkPool(Link *links, int count)
{
    if (g_linksUsed != 0) return;   // too late: keep the current pool
    g_pool = links;
    g_poolSize = count;
    g_poolNext = 0;
    g_freeLinks = nullptr;
}

LinkPoolStats linkPoolStats() { return {g_poolSize, g_linksUsed, g_linksPeak}; }

// ------------------------------------------------------------------ Observer

Observer::~Observer() { unlinkFromPending(); }

void Observer::markDirty()
{
    if (m_queued) return;
    m_queued = true;
    m_nextPending = nullptr;
    if (g_pendingTail) g_pendingTail->m_nextPending = this;
    else g_pendingHead = this;
    g_pendingTail = this;
}

void Observer::unlinkFromPending()
{
    if (!m_queued) return;
    Observer *prev = nullptr;
    for (Observer *o = g_pendingHead; o; prev = o, o = o->m_nextPending) {
        if (o != this) continue;
        if (prev) prev->m_nextPending = m_nextPending;
        else g_pendingHead = m_nextPending;
        if (g_pendingTail == this) g_pendingTail = prev;
        break;
    }
    m_queued = false;
    m_nextPending = nullptr;
}

void Observer::flush()
{
    if (g_flushing) return;
    g_flushing = true;
    BindingBase *saved = g_current;
    g_current = nullptr;               // handlers must not record dependencies
    uint32_t iterations = 0;
    while (Observer *o = g_pendingHead) {
        g_pendingHead = o->m_nextPending;
        if (!g_pendingHead) g_pendingTail = nullptr;
        o->m_queued = false;
        o->m_nextPending = nullptr;
        o->run();
        if (++iterations > kMaxFlushIterations)
            fatal("MicroQuick: binding loop detected");
    }
    g_current = saved;
    g_flushing = false;
}

// -------------------------------------------------------------- PropertyBase

PropertyBase::~PropertyBase()
{
    while (m_observers) removeLink(m_observers);
    if (m_binding) m_binding->m_target = nullptr;
}

void PropertyBase::addLink(Link *link)
{
    link->source = this;
    link->prev = nullptr;
    link->next = m_observers;
    if (m_observers) m_observers->prev = link;
    m_observers = link;
}

void PropertyBase::removeLink(Link *link)
{
    PropertyBase *src = link->source;
    if (!src) return;
    if (link->prev) link->prev->next = link->next;
    else src->m_observers = link->next;
    if (link->next) link->next->prev = link->prev;
    link->source = nullptr;
    link->next = link->prev = nullptr;
}

void PropertyBase::trackRead() const
{
    if (g_current) g_current->dependOn(this);
}

void PropertyBase::notify()
{
    for (Link *l = m_observers; l; l = l->next)
        l->observer->markDirty();
    if (m_owner) m_owner->propertyChanged(this, m_flags);
    Observer::flush();
}

void PropertyBase::setBinding(BindingBase *binding)
{
    removeBinding();
    m_binding = binding;
    binding->m_target = this;
    binding->m_attached = true;
    binding->run();
}

void PropertyBase::removeBinding()
{
    if (!m_binding) return;
    BindingBase *b = m_binding;
    m_binding = nullptr;
    b->detach();
}

// --------------------------------------------------------------- BindingBase

BindingBase *BindingBase::current() { return g_current; }

BindingBase *BindingBase::swapCurrent(BindingBase *binding)
{
    BindingBase *prev = g_current;
    g_current = binding;
    return prev;
}

BindingBase::~BindingBase()
{
    clearDeps();
    if (m_target && m_target->m_binding == this) m_target->m_binding = nullptr;
}

void BindingBase::clearDeps()
{
    while (Link *l = m_deps) {
        m_deps = l->nextOwned;
        PropertyBase::removeLink(l);
        freeLink(l);
    }
}

void BindingBase::detach()
{
    clearDeps();
    unlinkFromPending();
    m_attached = false;
}

void BindingBase::dependOn(const PropertyBase *source)
{
    if (!m_attached) return;
    PropertyBase *src = const_cast<PropertyBase *>(source);
    for (Link *l = m_deps; l; l = l->nextOwned)
        if (l->source == src) return;
    Link *l = allocLink();
    if (!l) return;
    l->observer = this;
    l->nextOwned = m_deps;
    m_deps = l;
    src->addLink(l);
}

void BindingBase::run()
{
    if (!m_attached) return;
    if (m_running) {
        fatal("MicroQuick: recursive binding evaluation");
        return;
    }
    m_running = true;
    clearDeps();
    BindingBase *saved = g_current;
    g_current = this;
    evaluate();   // Binding<T>::evaluate() resets g_current before storing
    g_current = saved;
    m_running = false;
}


} // namespace mq
