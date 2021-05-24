"""
Rez package tool/application launcher
"""
import os
import sys
import argparse
try:
    from rez.command import Command
except ImportError:
    Command = object


command_behavior = {}


def rez_cli():
    from rez.cli._main import run
    from rez.cli._entry_points import check_production_install
    check_production_install()
    try:
        return run("park")
    except KeyError:
        pass
        # for rez version that doesn't have Command type plugin
    return standalone_cli()


def standalone_cli():
    # for running without rez's cli
    parser = argparse.ArgumentParser("allzpark", description=(
        "An application launcher built on Rez, "
        "pass --help for details"
    ))
    parser.add_argument("-v", "--verbose", action="count", default=0, help=(
        "Print additional information about Allzpark during operation. "
        "Pass -v for info, -vv for info and -vvv for debug messages"))
    setup_parser(parser)
    opts = parser.parse_args()
    return command(opts)


def setup_parser(parser, completions=False):
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
    parser.add_argument("--version", action="store_true",
                        help="Print out version of this plugin command.")


def command(opts, parser=None, extra_arg_groups=None):
    from allzpark import cli, allzparkconfig

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
        from allzpark.version import print_info
        sys.exit(print_info())

    app, ctrl = cli.initialize(
        config_file=opts.config_file,
        verbose=opts.verbose,
        clean=opts.clean,
        demo=opts.demo,
        no_config=opts.no_config,
    )

    if opts.root:
        cli.warn("The flag --root has been deprecated, "
                 "use allzparkconfig.py:profiles.\n")

        def profiles_from_dir(path):
            try:
                _profiles = os.listdir(path)
            except IOError:
                cli.warn("ERROR: Could not list directory %s" % opts.root)
                _profiles = []
            # Support directory names that use dash in place of underscore
            _profiles = [p.replace("-", "_") for p in _profiles]
            return _profiles

        profiles = profiles_from_dir(opts.root)
    else:
        profiles = []

    cli.launch(ctrl)
    cli.reset(ctrl, profiles)

    app.exec_()


class AllzparkCommand(Command):
    schema_dict = {}

    @classmethod
    def name(cls):
        return "park"


def register_plugin():
    return AllzparkCommand
