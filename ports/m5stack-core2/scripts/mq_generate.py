# PlatformIO pre-build script: QML -> C++ and asset conversion for MicroQuick.
#
# 1. runs mqc (tools/mqc/mqc.py, pure Python) on the QML files listed in
#    platformio.ini (custom_mq_main, custom_mq_qml, custom_mq_assets);
# 2. runs mqassets (Qt 6 host tool) to rasterize the fonts and convert the
#    images. mqassets is looked up in this order:
#      - the MQ_ASSETS_EXECUTABLE environment variable,
#      - <repo>/build/tools/mqassets/mqassets (the desktop CMake build),
#      - <repo>/build-host/tools/mqassets/mqassets, built on demand with CMake
#        and Qt 6 (MQ_QT_DIR, or the newest ~/Qt/6.*/<host> found).
# The generated files go to src/mq_generated/ and are only rebuilt when a QML
# file, an asset, the font or the compiler changed.

Import("env")  # noqa: F821  (provided by PlatformIO / SCons)

import glob
import os
import platform
import shutil
import subprocess
import sys

PROJECT = env.subst("$PROJECT_DIR")  # noqa: F821
REPO = os.path.abspath(os.path.join(PROJECT, "..", ".."))
OUT = os.path.join(PROJECT, "src", "mq_generated")


def option(name, default=""):
    try:
        return env.GetProjectOption(name)  # noqa: F821
    except Exception:
        return default


def paths(value):
    return [os.path.abspath(os.path.join(PROJECT, p)) for p in value.split() if p.strip()]


def fail(msg):
    sys.stderr.write("MicroQuick: " + msg + "\n")
    env.Exit(1)  # noqa: F821


def newest(files):
    return max((os.path.getmtime(f) for f in files if os.path.exists(f)), default=0)


def find_qt():
    qt = os.environ.get("MQ_QT_DIR")
    if qt:
        return qt
    host = {"Darwin": "macos", "Linux": "gcc_64", "Windows": "msvc2022_64"}.get(platform.system(), "")
    candidates = sorted(glob.glob(os.path.expanduser(f"~/Qt/6.*/{host}")))
    return candidates[-1] if candidates else None


def find_mqassets():
    exe = os.environ.get("MQ_ASSETS_EXECUTABLE")
    if exe and os.path.exists(exe):
        return exe
    suffix = ".exe" if platform.system() == "Windows" else ""
    for d in ("build", "build-host"):
        exe = os.path.join(REPO, d, "tools", "mqassets", "mqassets" + suffix)
        if os.path.exists(exe):
            return exe
    # build it from the repository with CMake + Qt 6
    qt = find_qt()
    if not qt:
        fail("mqassets not found and no Qt 6 installation detected (set MQ_QT_DIR or MQ_ASSETS_EXECUTABLE)")
    cmake = shutil.which("cmake")
    if not cmake:
        fail("cmake is needed to build the mqassets host tool")
    build = os.path.join(REPO, "build-host")
    print(f"MicroQuick: building the mqassets host tool with Qt from {qt}")
    gen = ["-G", "Ninja"] if shutil.which("ninja") else []
    subprocess.check_call([cmake, "-S", REPO, "-B", build, *gen, f"-DCMAKE_PREFIX_PATH={qt}",
                           "-DMQ_BUILD_TESTS=OFF", "-DMQ_BUILD_EXAMPLES=OFF", "-DMQ_BUILD_SIMULATOR=OFF"])
    subprocess.check_call([cmake, "--build", build, "--target", "mqassets"])
    return os.path.join(build, "tools", "mqassets", "mqassets" + suffix)


def generate():
    main = paths(option("custom_mq_main"))
    if not main:
        fail("custom_mq_main is not set in platformio.ini")
    qml = paths(option("custom_mq_qml"))
    assets = paths(option("custom_mq_assets"))
    font = paths(option("custom_mq_font", "../../fonts/DejaVuSans.ttf"))[0]
    compiler = glob.glob(os.path.join(REPO, "tools", "mqc", "*.py"))
    inputs = main + qml + assets + [font] + compiler + [os.path.join(PROJECT, "platformio.ini")]
    for f in main + qml + assets + [font]:
        if not os.path.exists(f):
            fail(f"file not found: {f}")
    outputs = [os.path.join(OUT, n) for n in ("mq_app.h", "mq_app.cpp", "mq_assets.cpp")]
    if all(os.path.exists(o) for o in outputs) and min(os.path.getmtime(o) for o in outputs) >= newest(inputs):
        return

    os.makedirs(OUT, exist_ok=True)
    print("MicroQuick: compiling QML to C++ (mqc)")
    cmd = [sys.executable, os.path.join(REPO, "tools", "mqc", "mqc.py"), "--main", main[0], "--out", OUT]
    for a in assets:
        cmd += ["--asset", a]
    cmd += qml
    if subprocess.call(cmd) != 0:
        fail("QML compilation failed (see the errors above)")

    print("MicroQuick: rasterizing fonts and converting images (mqassets)")
    mqassets = find_mqassets()
    if subprocess.call([mqassets, "--manifest", os.path.join(OUT, "mq_assets.txt"), "--font", font,
                        "--out", os.path.join(OUT, "mq_assets.cpp")]) != 0:
        fail("asset conversion failed")


generate()
