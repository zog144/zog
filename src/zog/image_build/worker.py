"""Maintained build workers; historical deployment handoffs are not entry points."""
import argparse
import importlib
import sys

WORKERS = {
    "stages": "zog.image_build.stages",
    "native-stage": "zog.image_build.native_stage",
    "glibc-final": "zog.image_build.glibc_final",
    "glibc-publish": "zog.image_build.glibc_publish",
    "final-math": "zog.image_build.final_math",
    "final-compiler": "zog.image_build.final_compiler",
}

def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker", choices=WORKERS)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)
    previous = sys.argv
    try:
        sys.argv = ["image-build-worker " + options.worker, *options.arguments]
        return importlib.import_module(WORKERS[options.worker]).main()
    finally:
        sys.argv = previous

if __name__ == "__main__":
    main()
