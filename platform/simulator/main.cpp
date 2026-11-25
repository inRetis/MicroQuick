// MicroQuick desktop simulator, built on the user's Qt 6 installation.
// It plays the role of a board support package: it owns the RGB565
// framebuffer, feeds the runtime with time and pointer events, and shows the
// framebuffer in a window (optionally zoomed).
//
// Options:
//   --zoom N                 window scale factor (default 2)
//   --script "cmds"          automation, ';' separated commands:
//                              wait MS | press X Y | move X Y | release X Y | click X Y
//                              screenshot FILE.png | quit
//   --offscreen              no window (use with --script)

#include <QtCore/QCommandLineParser>
#include <QtCore/QElapsedTimer>
#include <QtCore/QTimer>
#include <QtGui/QGuiApplication>
#include <QtGui/QImage>
#include <QtGui/QMouseEvent>
#include <QtGui/QPainter>
#include <QtGui/QRasterWindow>

#include <mq/mq.h>
#include <cstdio>
#include <vector>

mq::Item *mq_app_root();

namespace {

class Simulator : public QRasterWindow {
public:
    Simulator(int w, int h, int zoom) : m_fb(size_t(w) * h, 0), m_w(w), m_h(h), m_zoom(zoom)
    {
        mq::Window *win = mq::Window::instance();
        win->setFramebuffer(m_fb.data(), w, h);
        win->setRoot(mq_app_root());
        setTitle(QStringLiteral("MicroQuick simulator — %1x%2 RGB565").arg(w).arg(h));
        resize(w * zoom, h * zoom);
        m_clock.start();
        connect(&m_tick, &QTimer::timeout, this, [this] { frame(); });
        m_tick.start(8);
        frame();
    }

    QImage image() const
    {
        return QImage(reinterpret_cast<const uchar *>(m_fb.data()), m_w, m_h, m_w * 2,
                      QImage::Format_RGB16).copy();
    }

    void pointer(mq::PointerAction a, int x, int y)
    {
        mq::Window::instance()->pointerEvent(a, x, y);
        frame();
    }

    void frame()
    {
        mq::Rect dirty[MQ_MAX_DIRTY_RECTS];
        int n = mq::Window::instance()->processFrame(uint32_t(m_clock.elapsed()), dirty);
        if (n > 0) update();
    }

protected:
    void paintEvent(QPaintEvent *) override
    {
        QPainter p(this);
        p.drawImage(QRect(0, 0, m_w * m_zoom, m_h * m_zoom), image());
    }
    void mousePressEvent(QMouseEvent *e) override { send(mq::PointerAction::Press, e); }
    void mouseMoveEvent(QMouseEvent *e) override
    {
        if (e->buttons() & Qt::LeftButton) send(mq::PointerAction::Move, e);
    }
    void mouseReleaseEvent(QMouseEvent *e) override { send(mq::PointerAction::Release, e); }

private:
    void send(mq::PointerAction a, QMouseEvent *e)
    {
        pointer(a, int(e->position().x()) / m_zoom, int(e->position().y()) / m_zoom);
    }

    std::vector<uint16_t> m_fb;
    int m_w, m_h, m_zoom;
    QElapsedTimer m_clock;
    QTimer m_tick;
};

void runScript(Simulator *sim, QStringList cmds)
{
    while (!cmds.isEmpty()) {
        const QStringList c = cmds.takeFirst().trimmed().split(' ', Qt::SkipEmptyParts);
        if (c.isEmpty()) continue;
        const QString op = c[0];
        if (op == "wait") {
            QTimer::singleShot(c.value(1).toInt(), sim, [sim, cmds] { runScript(sim, cmds); });
            return;
        } else if (op == "move") {
            sim->pointer(mq::PointerAction::Move, c.value(1).toInt(), c.value(2).toInt());
        } else if (op == "press" || op == "release" || op == "click") {
            const int x = c.value(1).toInt(), y = c.value(2).toInt();
            if (op != "release") sim->pointer(mq::PointerAction::Press, x, y);
            if (op != "press") sim->pointer(mq::PointerAction::Release, x, y);
        } else if (op == "screenshot") {
            sim->frame();
            if (!sim->image().save(c.value(1))) fprintf(stderr, "cannot save %s\n", qPrintable(c.value(1)));
        } else if (op == "quit") {
            QTimer::singleShot(0, qApp, &QCoreApplication::quit);
            return;
        } else {
            fprintf(stderr, "unknown script command: %s\n", qPrintable(op));
        }
    }
}

} // namespace

int main(int argc, char **argv)
{
    for (int i = 1; i < argc; ++i)
        if (qstrcmp(argv[i], "--offscreen") == 0) qputenv("QT_QPA_PLATFORM", "offscreen");
    QGuiApplication app(argc, argv);
    QCommandLineParser cli;
    cli.setApplicationDescription("MicroQuick simulator");
    cli.addHelpOption();
    cli.addOption({"zoom", "Window scale factor.", "n", "2"});
    cli.addOption({"script", "Automation commands separated by ';'.", "cmds"});
    cli.addOption({"offscreen", "Do not show a window."});
    cli.process(app);

    mq::Item *root = mq_app_root();
    const int w = root->width.value() > 0 ? root->width.value() : 480;
    const int h = root->height.value() > 0 ? root->height.value() : 272;
    Simulator sim(w, h, qMax(1, cli.value("zoom").toInt()));
    if (!cli.isSet("offscreen")) sim.show();
    if (cli.isSet("script"))
        QTimer::singleShot(0, &sim, [&] { runScript(&sim, cli.value("script").split(';')); });
    const int rc = app.exec();
    const mq::LinkPoolStats links = mq::linkPoolStats();
    fprintf(stderr, "MicroQuick: dependency links peak %d / %d reserved\n", links.peak, links.size);
    return rc;
}
