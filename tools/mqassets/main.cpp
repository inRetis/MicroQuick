// mqassets: host tool (built with Qt 6) converting the asset manifest written
// by mqc into C++ constant data for the MicroQuick runtime:
//   * fonts are pre-rasterized as 8-bit anti-aliased glyphs, only for the
//     pixel sizes and characters used by the application;
//   * images are converted to RGB565 (opaque) or ARGB8888 (with alpha).
//
// usage: mqassets --manifest mq_assets.txt --font font.ttf --out mq_assets.cpp

#include <QtCore/QCommandLineParser>
#include <QtCore/QFile>
#include <QtCore/QFileInfo>
#include <QtCore/QTextStream>
#include <QtGui/QFont>
#include <QtGui/QFontDatabase>
#include <QtGui/QFontMetrics>
#include <QtGui/QGuiApplication>
#include <QtGui/QImage>
#include <QtGui/QPainter>

#include <cstdio>
#include <vector>

namespace {

struct GlyphOut {
    uint32_t cp;
    int left, top, width, height, advance;
    uint32_t offset;
};

void writeBytes(QTextStream &out, const std::vector<uint8_t> &bytes)
{
    for (size_t i = 0; i < bytes.size(); ++i) {
        if (i % 24 == 0) out << "\n    ";
        out << bytes[i] << ",";
    }
    out << "\n";
}

bool rasterizeFont(QTextStream &out, const QString &family, int pixelSize,
                   const std::vector<uint32_t> &charset, QString &symbol)
{
    QFont font(family);
    font.setPixelSize(pixelSize);
    font.setHintingPreference(QFont::PreferFullHinting);
    font.setStyleStrategy(QFont::PreferAntialias);
    font.setKerning(false);
    QFontMetrics fm(font);

    std::vector<GlyphOut> glyphs;
    std::vector<uint8_t> alpha;
    const int canvasW = pixelSize * 4, canvasH = fm.height() * 2 + pixelSize;
    const int originX = pixelSize, baseline = fm.ascent() + pixelSize / 2;

    for (uint32_t cp : charset) {
        if (cp != ' ' && !fm.inFontUcs4(cp)) continue;
        const QString s = QString::fromUcs4(reinterpret_cast<const char32_t *>(&cp), 1);
        QImage img(canvasW, canvasH, QImage::Format_ARGB32_Premultiplied);
        img.fill(Qt::transparent);
        {
            QPainter p(&img);
            p.setFont(font);
            p.setPen(Qt::white);
            p.drawText(originX, baseline, s);
        }
        int minX = canvasW, minY = canvasH, maxX = -1, maxY = -1;
        for (int y = 0; y < canvasH; ++y) {
            const QRgb *row = reinterpret_cast<const QRgb *>(img.constScanLine(y));
            for (int x = 0; x < canvasW; ++x) {
                if (qAlpha(row[x])) {
                    minX = qMin(minX, x); maxX = qMax(maxX, x);
                    minY = qMin(minY, y); maxY = qMax(maxY, y);
                }
            }
        }
        GlyphOut g{cp, 0, 0, 0, 0, qRound(QFontMetricsF(font).horizontalAdvance(s)), uint32_t(alpha.size())};
        if (maxX >= 0) {
            g.left = minX - originX;
            g.top = minY - baseline;
            g.width = maxX - minX + 1;
            g.height = maxY - minY + 1;
            if (g.width > 255 || g.height > 255) {
                fprintf(stderr, "mqassets: glyph U+%04X too large\n", cp);
                return false;
            }
            for (int y = minY; y <= maxY; ++y) {
                const QRgb *row = reinterpret_cast<const QRgb *>(img.constScanLine(y));
                for (int x = minX; x <= maxX; ++x) alpha.push_back(uint8_t(qAlpha(row[x])));
            }
        }
        glyphs.push_back(g);
    }

    symbol = QStringLiteral("mq_font_%1").arg(pixelSize);
    out << "// " << family << " " << pixelSize << "px: " << glyphs.size() << " glyphs, "
        << alpha.size() << " bytes of coverage\n";
    out << "static const uint8_t " << symbol << "_alpha[] = {";
    if (alpha.empty()) alpha.push_back(0);
    writeBytes(out, alpha);
    out << "};\n";
    out << "static const mq::Glyph " << symbol << "_glyphs[] = {\n";
    for (const GlyphOut &g : glyphs) {
        out << "    {0x" << Qt::hex << g.cp << Qt::dec << ", " << g.left << ", " << g.top << ", "
            << g.width << ", " << g.height << ", " << g.advance << ", " << g.offset << "},\n";
    }
    out << "};\n";
    out << "static const mq::FontData " << symbol << " = {" << pixelSize << ", " << fm.ascent() << ", "
        << fm.descent() << ", " << fm.height() << ", " << glyphs.size() << ", " << symbol
        << "_glyphs, " << symbol << "_alpha};\n\n";
    return true;
}

bool convertImage(QTextStream &out, const QString &symbol, const QString &path)
{
    QImage img(path);
    if (img.isNull()) {
        fprintf(stderr, "mqassets: cannot load image %s\n", qPrintable(path));
        return false;
    }
    const bool alpha = img.hasAlphaChannel();
    out << "// " << QFileInfo(path).fileName() << " " << img.width() << "x" << img.height()
        << (alpha ? " ARGB8888" : " RGB565") << "\n";
    if (alpha) {
        img = img.convertToFormat(QImage::Format_ARGB32);
        out << "static const uint32_t " << symbol << "_pixels[] = {";
        int n = 0;
        for (int y = 0; y < img.height(); ++y) {
            const QRgb *row = reinterpret_cast<const QRgb *>(img.constScanLine(y));
            for (int x = 0; x < img.width(); ++x, ++n) {
                if (n % 8 == 0) out << "\n    ";
                out << "0x" << QString::number(row[x], 16).rightJustified(8, QLatin1Char('0')) << "u,";
            }
        }
    } else {
        img = img.convertToFormat(QImage::Format_RGB16);
        out << "static const uint16_t " << symbol << "_pixels[] = {";
        int n = 0;
        for (int y = 0; y < img.height(); ++y) {
            const quint16 *row = reinterpret_cast<const quint16 *>(img.constScanLine(y));
            for (int x = 0; x < img.width(); ++x, ++n) {
                if (n % 12 == 0) out << "\n    ";
                out << "0x" << QString::number(row[x], 16).rightJustified(4, QLatin1Char('0')) << ",";
            }
        }
    }
    out << "\n};\n";
    out << "extern const mq::ImageData " << symbol << ";\n";
    out << "const mq::ImageData " << symbol << " = {" << img.width() << ", " << img.height() << ", "
        << (alpha ? "mq::PixelFormat::ARGB8888" : "mq::PixelFormat::RGB565") << ", " << symbol
        << "_pixels};\n\n";
    return true;
}

} // namespace

int main(int argc, char **argv)
{
    qputenv("QT_QPA_PLATFORM", "offscreen");
    QGuiApplication app(argc, argv);
    QCommandLineParser cli;
    cli.setApplicationDescription("MicroQuick asset compiler");
    cli.addHelpOption();
    cli.addOption({"manifest", "Asset manifest written by mqc.", "file"});
    cli.addOption({"font", "TrueType font to rasterize.", "file"});
    cli.addOption({"out", "Output C++ file.", "file"});
    cli.process(app);
    if (!cli.isSet("manifest") || !cli.isSet("font") || !cli.isSet("out")) cli.showHelp(1);

    QFile manifest(cli.value("manifest"));
    if (!manifest.open(QIODevice::ReadOnly | QIODevice::Text)) {
        fprintf(stderr, "mqassets: cannot read %s\n", qPrintable(manifest.fileName()));
        return 1;
    }
    std::vector<int> sizes;
    std::vector<uint32_t> charset;
    std::vector<std::pair<QString, QString>> images;
    while (!manifest.atEnd()) {
        const QString line = QString::fromUtf8(manifest.readLine()).trimmed();
        if (line.startsWith("font_sizes ")) {
            for (const QString &s : line.mid(11).split(' ', Qt::SkipEmptyParts)) sizes.push_back(s.toInt());
        } else if (line.startsWith("charset ")) {
            for (const QString &s : line.mid(8).split(' ', Qt::SkipEmptyParts)) charset.push_back(s.toUInt(nullptr, 16));
        } else if (line.startsWith("image ")) {
            const QString rest = line.mid(6);
            const int sp = rest.indexOf(' ');
            images.emplace_back(rest.left(sp), rest.mid(sp + 1));
        }
    }

    const int fontId = QFontDatabase::addApplicationFont(cli.value("font"));
    if (fontId < 0) {
        fprintf(stderr, "mqassets: cannot load font %s\n", qPrintable(cli.value("font")));
        return 1;
    }
    const QString family = QFontDatabase::applicationFontFamilies(fontId).value(0);

    QString text;
    QTextStream out(&text);
    out << "// Generated by mqassets (MicroQuick). Do not edit.\n#include <mq/resources.h>\n\n";
    QStringList fontSymbols;
    for (int size : sizes) {
        QString sym;
        if (!rasterizeFont(out, family, size, charset, sym)) return 1;
        fontSymbols << "&" + sym;
    }
    out << "extern const mq::FontData *const mq_fonts[];\n";
    out << "const mq::FontData *const mq_fonts[] = {" << fontSymbols.join(", ") << "};\n";
    out << "extern const int mq_font_count;\n";
    out << "const int mq_font_count = " << fontSymbols.size() << ";\n\n";
    for (const auto &img : images)
        if (!convertImage(out, img.first, img.second)) return 1;
    out.flush();

    QFile file(cli.value("out"));
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        fprintf(stderr, "mqassets: cannot write %s\n", qPrintable(file.fileName()));
        return 1;
    }
    file.write(text.toUtf8());
    return 0;
}
