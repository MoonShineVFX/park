"""Command-line interface to allzpark"""

import os
import sys
import time
import signal
import logging
import argparse
import contextlib

from .version import version
from . import allzparkconfig

timing = {}
log = logging.getLogger("allzpark")
UserError = type("UserError", (Exception,), {})


def _load_userconfig(fname=None):
    fname = fname or os.getenv(
        "ALLZPARK_CONFIG_FILE",
        os.path.expanduser("~/allzparkconfig.py")
    )

    mod = {
        "__file__": fname,
    }

    try:
        with open(fname) as f:
            exec(compile(f.read(), f.name, 'exec'), mod)

    except IOError:
        raise

    except Exception:
        raise UserError("Better double-check your user config")

    for key in dir(allzparkconfig):
        if key.startswith("__"):
            continue

        try:
            value = mod[key]
        except KeyError:
            continue

        setattr(allzparkconfig, key, value)

    return fname


def _backwards_compatibility():
    # The term "project" was renamed "profile" in version 1.2.100
    if hasattr(allzparkconfig, "projects"):
        allzparkconfig.profiles = allzparkconfig.projects

    if hasattr(allzparkconfig, "startup_project"):
        allzparkconfig.startup_profile = allzparkconfig.startup_project


def _patch_allzparkconfig():
    """Make backup copies of originals, with `_` prefix

    Useful for augmenting an existing value with your own config

    """

    for member in dir(allzparkconfig):
        if member.startswith("__"):
            continue

        setattr(allzparkconfig, "_%s" % member,
                getattr(allzparkconfig, member))


@contextlib.contextmanager
def timings(title, timing=True):
    tell(title, newlines=0)
    t0 = time.time()
    message = {"success": "ok - {:.2f}\n" if timing else "ok\n",
               "failure": "fail\n",
               "ignoreFailure": False}

    try:
        yield message

    except Exception:
        tell(message["failure"], 0)

        if log.level < logging.WARNING:
            import traceback
            tell(traceback.format_exc())

        else:
            tell("Pass --verbose for details")

        exit(1)
    else:
        tell(message["success"].format(time.time() - t0), 0)


def tell(msg, newlines=1):
    sys.stdout.write(("%s" + "\n" * newlines) % msg)


def warn(msg, newlines=1):
    sys.stderr.write(("%s" + "\n" * newlines) % msg)


def main():
    parser = argparse.ArgumentParser("allzpark", description=(
        "An application launcher built on Rez, "
        "pass --help for details"
    ))

    parser.add_argument("-v", "--verbose", action="count", default=0, help=(
        "Print additional information about Allzpark during operation. "
        "Pass -v for info, -vv for info and -vvv for debug messages"))
    parser.add_argument("--version", action="store_true", help=(
        "Print version and exit"))
    parser.add_argument("--clean", action="store_true", help=(
        "Start fresh with user preferences"))
    parser.add_argument("--config-file", type=str, help=(
        "Absolute path to allzparkconfig.py, takes precedence "
        "over ALLZPARK_CONFIG_FILE"))
    parser.add_argument("--no-config", action="store_true", help=(
        "Do not load custom allzparkconfig.py"))
    parser.add_argument("--demo", action="store_true", help=(
        "Run demo material"))
    parser.add_argument("--root", help=(
        "(DEPRECATED) Path to where profiles live on disk, "
        "defaults to allzparkconfig.profiles"))

    opts = parser.parse_args()

    if not sys.stdout:
        import tempfile

        # Capture early messages from a console-less session
        # Primarily intended for Windows's pythonw.exe
        # (Handles close automatically on exit)
        temproot = tempfile.gettempdir()
        sys.stdout = open(os.path.join(temproot, "allzpark-stdout.txt"), "a")
        sys.stderr = open(os.path.join(temproot, "allzpark-stderr.txt"), "a")

        # We don't need it, but Rez uses this internally
        sys.stdin = open(os.path.join(temproot, "allzpark-stdin.txt"), "w")

        # Rez references these originals too
        sys.__stdout__ = sys.stdout
        sys.__stderr__ = sys.stderr
        sys.__stdin__ = sys.stdin

        opts.verbose = 3
        allzparkconfig.__noconsole__ = True

    if opts.version:
        tell(version)
        exit(0)

    tell("=" * 30)
    tell(" allzpark (%s)" % version)
    tell("=" * 30)

    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(levelname)-8s %(name)s %(message)s"
        if opts.verbose
        else "%(message)s"
    )

    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG
                 if opts.verbose >= 2
                 else logging.INFO
                 if opts.verbose == 1
                 else logging.WARNING)

    logging.getLogger("allzpark.vendor").setLevel(logging.CRITICAL)

    if opts.demo:
        with timings("- Loading demo..") as msg:
            try:
                import allzparkdemo
            except ImportError:
                msg["failure"] = (
                    " fail\n"
                    "ERROR: The --demo flag requires allzparkdemo, "
                    "try running `pip install allzparkdemo`\n"
                )
                raise

            os.environ["REZ_CONFIG_FILE"] = allzparkdemo.rezconfig
            opts.config_file = allzparkdemo.allzparkconfig

        tell("  - %s" % allzparkdemo.rezconfig)
        tell("  - %s" % allzparkdemo.allzparkconfig)

    with timings("- Loading Rez.. ") as msg:
        try:
            from rez import __file__ as _rez_location
            from rez.utils._version import _rez_version
            from rez.config import config
            msg["success"] = "(%s) - ok {:.2f}\n" % _rez_version
        except ImportError:
            tell("ERROR: allzpark requires rez")
            exit(1)

    with timings("- Loading Qt.. ") as msg:
        try:
            from .vendor import Qt
            msg["success"] = "(%s) - ok {:.2f}\n" % Qt.__binding__
        except ImportError:
            msg["failure"] = (
                "ERROR: allzpark requires a Python binding for Qt,\n"
                "such as PySide, PySide2, PyQt4 or PyQt5.\n"
            )

        from .vendor import six
        from .vendor.Qt import QtWidgets, QtCore

    # Provide for vendor dependencies
    sys.modules["Qt"] = Qt
    sys.modules["six"] = six

    with timings("- Loading allzpark.. ") as msg:
        from . import view, control, resources, util
        msg["success"] = "(%s) - ok {:.2f}\n" % version

    _patch_allzparkconfig()

    with timings("- Loading allzparkconfig.. ") as msg:
        try:
            result = _load_userconfig(opts.config_file)
            msg["success"] = "ok {:.2f} (%s)\n" % result

        except IOError:
            pass

    _backwards_compatibility()

    # Allow the application to die on CTRL+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    config.catch_rex_errors = False

    with timings("- Loading preferences.. "):
        storage = QtCore.QSettings(QtCore.QSettings.IniFormat,
                                   QtCore.QSettings.UserScope,
                                   "Allzpark", "preferences")

        try:
            storage.value("startupApp")
        except ValueError:
            # Likely settings stored with a previous version of Python
            raise ValueError("Your settings could not be read, "
                             "have they been created using a different "
                             "version of Python? You can either use "
                             "the same version or pass "
                             "--clean to erase your previous settings and "
                             "start anew")

        if opts.clean:
            tell("(clean) ")
            storage.clear()

        defaults = {
            "memcachedURI": os.getenv("REZ_MEMCACHED_URI", "None"),
            "pythonExe": sys.executable,
            "pythonVersion": ".".join(map(str, sys.version_info)),
            "qtVersion": Qt.__binding_version__,
            "qtBinding": Qt.__binding__,
            "qtBindingVersion": Qt.__qt_version__,
            "rezLocation": os.path.dirname(_rez_location),
            "rezVersion": _rez_version,
            "rezConfigFile": os.getenv("REZ_CONFIG_FILE", "None"),
            "rezPackagesPath": config.packages_path,
            "rezLocalPath": config.local_packages_path.split(os.pathsep),
            "rezReleasePath": config.release_packages_path.split(os.pathsep),
            "settingsPath": storage.fileName(),
        }

        for key, value in defaults.items():
            storage.setValue(key, value)

        if allzparkconfig.startup_profile:
            storage.setValue("startupProfile", allzparkconfig.startup_profile)

        if allzparkconfig.startup_application:
            storage.setValue("startupApp", allzparkconfig.startup_application)

        if opts.demo:
            # Normally unsafe, but for the purposes of a demo
            # a convenient location for installed packages
            storage.setValue("useDevelopmentPackages", True)

    try:
        __import__("localz")
        allzparkconfig._localz_enabled = True
    except ImportError:
        allzparkconfig._localz_enabled = False

    tell("-" * 30)  # Add some space between boot messages, and upcoming log

    app = QtWidgets.QApplication([])
    ctrl = control.Controller(storage)

    # Handle stdio from within the application if necessary
    if hasattr(allzparkconfig, "__noconsole__"):
        sys.stdout = ctrl.stdio(sys.stdout, logging.INFO)
        sys.stderr = ctrl.stdio(sys.stderr, logging.ERROR)

        # TODO: This isn't fool proof. There are logging mechanisms
        # in control.py that must either print to stdio or not and
        # there's currently some duplication.

    def excepthook(type, value, traceback):
        """Try handling these from within the controller"""

        # Give handler a chance to remedy the situation
        handled = ctrl.on_unhandled_exception(type, value, traceback)

        if not handled:
            sys.__excepthook__(type, value, traceback)

    sys.excepthook = excepthook

    window = view.Window(ctrl)
    user_css = storage.value("userCss") or ""
    custom_css = allzparkconfig.style_loader() or ""

    with open(resources.find("style.css")) as f:
        css = f.read()
        originalcss = "\n".join([css, custom_css])

        # Store for CSS Editor
        window._originalcss = originalcss

        window.setStyleSheet("\n".join([originalcss, user_css]))

    window.show()

    def profiles_from_dir(path):
        try:
            profiles = os.listdir(opts.root)
        except IOError:
            warn(
                "ERROR: Could not list directory %s" % opts.root
            )

        # Support directory names that use dash in place of underscore
        profiles = [p.replace("-", "_") for p in profiles]

        return profiles

    def init():
        timing["beforeReset"] = time.time()
        profiles = []

        if opts.root:
            warn("The flag --root has been deprecated, "
                 "use allzparkconfig.py:profiles.\n")
            profiles = profiles_from_dir(opts.root)

        root = profiles or allzparkconfig.profiles
        ctrl.reset(root, on_success=measure)

    def measure():
        duration = time.time() - timing["beforeReset"]
        tell("- Resolved contexts.. ok %.2fs" % duration)

    # Give the window a moment to appear before occupying it
    QtCore.QTimer.singleShot(50, init)

    if os.name == "nt":
        util.windows_taskbar_compat()

    app.exec_()
