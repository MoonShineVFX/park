"""
Rez suite based package tool/application launcher
"""
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
        "Start fresh with user preferences"))  # todo: not implemented
    parser.add_argument("--version", action="store_true",
                        help="Print out version of this plugin command.")
    parser.add_argument("--gui", action="store_true")


def command(opts, parser=None, extra_arg_groups=None):
    import logging
    from allzpark import cli, report
    report.init_logging()

    if opts.debug:
        log = logging.getLogger("allzpark")
        stream_handler = next(h for h in log.handlers if h.name == "stream")
        stream_handler.setLevel(logging.DEBUG)

    if opts.version:
        from allzpark._version import print_info
        sys.exit(print_info())

    if opts.gui:
        from allzpark.gui import app
        sys.exit(app.launch())

    return cli.main()


class AllzparkCommand(Command):
    schema_dict = {}

    @classmethod
    def name(cls):
        return "park"


def register_plugin():
    return AllzparkCommand
