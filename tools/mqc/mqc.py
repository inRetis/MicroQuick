#!/usr/bin/env python3
"""mqc - MicroQuick QML compiler.

Translates a set of .qml files into C++ classes using the MicroQuick runtime
and writes an asset manifest (font sizes, characters, images) for mqassets.

usage: mqc.py --main Main.qml --out DIR file1.qml file2.qml ...
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import QmlError          # noqa: E402
from codegen import Generator        # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="MicroQuick QML to C++ compiler")
    ap.add_argument("--main", required=True, help="main (root) QML file")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--asset", action="append", default=[],
                    help="extra image to embed (reachable from computed Image sources)")
    ap.add_argument("files", nargs="*", help="other QML component files")
    args = ap.parse_args(argv)

    files = [os.path.abspath(f) for f in [args.main] + args.files]
    files = list(dict.fromkeys(files))
    gen = Generator()
    try:
        gen.compile(files, os.path.abspath(args.main), [os.path.abspath(a) for a in args.asset])
        gen.write(args.out)
        gen.write_manifest(os.path.join(args.out, "mq_assets.txt"))
    except QmlError as e:
        print(str(e), file=sys.stderr)
        return 1
    for w in gen.warnings:
        print(w, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
