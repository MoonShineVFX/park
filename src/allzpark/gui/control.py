
import os
import time
import logging
import inspect
import traceback
import functools
import threading
import subprocess
from rez.config import config as rezconfig
from ._vendor.Qt5 import QtCore
from .widgets import BusyWidget
from .. import core, util


log = logging.getLogger("allzpark")

allzparkconfig = rezconfig.plugins.command.park


def _defer(on_time=500):
    """A decorator for deferring Controller function call

    :param on_time: The time to wait before the function runs (msec)
    :type on_time: int
    :return:
    """
    def decorator(func):
        @functools.wraps(func)
        def decorated(*args, **kwargs):
            self = args[0]
            fn_name = func.__name__
            self._sender[fn_name] = QtCore.QObject.sender(self)  # real sender
            if fn_name not in self._timers:
                # init timer
                d = {
                    "timer": QtCore.QTimer(self),
                    "args": tuple(),
                    "kwargs": dict(),
                }
                self._timers[fn_name] = d

                def on_timeout():
                    func(*d["args"], **d["kwargs"])
                    self._sender.pop(fn_name, None)  # cleanup

                d["timer"].timeout.connect(on_timeout)
                d["timer"].setSingleShot(True)

            d = self._timers[fn_name]
            d["args"] = args
            d["kwargs"] = kwargs
            d["timer"].start(kwargs.get("on_time") or on_time)

        return decorated

    return decorator


def _thread(name, blocks=None):
    """A decorator for running Controller functions in worker thread

    :param name: Thread name
    :param blocks: A tuple of `BusyWidget` object name strings
    :type name: str
    :type blocks: tuple[str] or None
    :return:
    """
    # todo:
    #  closing app while thread running ->
    #   QThread: Destroyed while thread is still running

    def decorator(func):
        @functools.wraps(func)
        def decorated(*args, **kwargs):
            self = args[0]  # type: Controller
            fn_name = func.__name__

            if name not in self._thread:
                self._thread[name] = Thread(self)
            thread = self._thread[name]

            if thread.isRunning():
                log.critical(
                    f"Thread {name!r} is busy, can't process {fn_name!r}."
                )
                return

            blocks_ = blocks or []
            busy_widgets = [
                w for w in BusyWidget.instances() if w.objectName() in blocks_
            ]  # type: list[BusyWidget]

            for widget in busy_widgets:
                widget.set_overwhelmed(name)

            def on_finished():
                for w in busy_widgets:
                    w.pop_overwhelmed(name)
                thread.finished.disconnect(on_finished)
                log.debug(f"Thread {name!r} finished {fn_name!r}.")

            thread.finished.connect(on_finished)

            log.debug(f"Thread {name!r} is about to run {fn_name!r}.")
            thread.set_job(func, *args, **kwargs)
            thread.start()

        return decorated
    return decorator


class Controller(QtCore.QObject):
    workspace_entered = QtCore.Signal(core.AbstractScope)
    workspace_updated = QtCore.Signal(list)
    work_dir_obtained = QtCore.Signal(str)
    work_dir_resetted = QtCore.Signal()
    tools_updated = QtCore.Signal(list)
    tool_selected = QtCore.Signal(core.SuiteTool, dict)
    status_message = QtCore.Signal(str)
    cache_cleared = QtCore.Signal()

    def __init__(self, backends):
        super(Controller, self).__init__(parent=None)
        # note:
        #   we may need a state machine, for handling complex signal-slot
        #   connections.

        # sending log messages to status-bar
        formatter = logging.Formatter(fmt="%(levelname)-8s %(message)s")
        handler = QtStatusBarHandler(self)
        handler.set_name("gui")
        handler.setFormatter(formatter)
        handler.setLevel(logging.INFO)
        log.addHandler(handler)

        self._cwd = None
        self._env = None
        self._backend_entrances = dict(backends)
        self._timers = dict()
        self._sender = dict()
        self._thread = dict()  # type: dict[str, Thread]

    def sender(self):
        """Internal use. To preserve real signal sender for decorated method."""
        f = inspect.stack()[1].function
        return self._sender.pop(f, super(Controller, self).sender())

    @QtCore.Slot(core.AbstractScope)  # noqa
    @_defer(on_time=250)
    def on_backend_changed(self, entrance):
        scope = self._backend_entrances[entrance]
        self.enter_workspace(scope)

    @QtCore.Slot(core.AbstractScope)  # noqa
    def on_workspace_changed(self, scope):
        self.enter_workspace(scope)

    @QtCore.Slot(core.AbstractScope, bool)  # noqa
    @_defer(on_time=200)
    def on_workspace_refreshed(self, scope, cache_clear):
        self.update_workspace(scope, cache_clear)

    @QtCore.Slot(core.AbstractScope)  # noqa
    @_defer(on_time=100)
    def on_scope_tools_requested(self, scope):
        self.update_tools(scope)

    @QtCore.Slot(core.SuiteTool)  # noqa
    @_defer(on_time=50)
    def on_tool_selected(self, suite_tool: core.SuiteTool):
        self.select_tool(suite_tool)

    @QtCore.Slot(core.SuiteTool)  # noqa
    @_defer(on_time=200)
    def on_tool_launched(self, suite_tool: core.SuiteTool):
        self.launch(suite_tool, shell=False)

    @QtCore.Slot(core.SuiteTool)  # noqa
    @_defer(on_time=200)
    def on_shell_launched(self, suite_tool: core.SuiteTool):
        self.launch(suite_tool, shell=True)

    @QtCore.Slot()  # noqa
    @_defer(on_time=50)
    def on_cache_clear_clicked(self):
        self.cache_clear()

    def enter_workspace(self, scope):
        self.work_dir_resetted.emit()
        # inform widget to e.g. change page
        self.workspace_entered.emit(scope)

    @_thread(name="workspace", blocks=("ProductionPage",))
    def update_workspace(self, scope, cache_clear=False):
        if cache_clear:
            self.cache_clear()

        error_occurred, child_scopes = self.list_scopes(scope)
        if error_occurred:
            self.cache_clear()

        self.workspace_updated.emit(child_scopes)

    @_thread(name="tools", blocks=("ProductionPage",))
    def update_tools(self, scope):
        self.work_dir_resetted.emit()
        self.tools_updated.emit(core.list_tools(scope))
        self._cwd = None
        self._env = None

    @functools.lru_cache(maxsize=None)
    def list_scopes(self, scope):
        _error = False
        _start = time.time()
        children = []
        try:
            for i, child in enumerate(scope.iter_children()):
                children.append(child)
                log.info(f"Pulling{'.' * (int(i / 2) % 5): <5} {child.name}")
        except Exception as e:
            log.error(traceback.format_exc())
            log.error(str(e))
            _error = True

        if not _error:
            log.info(f"Workspace {scope.name} updated in "
                     f"{time.time() - _start:.2f} secs.")

        return _error, children

    def select_tool(self, suite_tool: core.SuiteTool):
        work_dir = suite_tool.scope.obtain_workspace(suite_tool)
        work_env = suite_tool.scope.additional_env(suite_tool)
        self.work_dir_obtained.emit(work_dir or "")
        self.tool_selected.emit(suite_tool, work_env or {})
        self._cwd = work_dir
        self._env = work_env

    def cache_clear(self):
        core.cache_clear()
        self.list_scopes.cache_clear()
        self.cache_cleared.emit()
        log.debug("Internal cache cleared.")

    def launch(self, tool: core.SuiteTool, shell=False):
        env = None
        if self._env:
            env = os.environ.copy()
            env.update(self._env)

        if not os.path.isdir(self._cwd):
            try:
                os.makedirs(self._cwd)
            except Exception as e:
                log.critical(str(e))
                return

        if shell:
            self._launch_shell(tool, env)
        else:
            self._launch_tool(tool, env)

    def _launch_shell(self, suite_tool: core.SuiteTool, env=None):
        log.info(f"Launching {suite_tool.name} shell...")

        suite_tool.context.execute_shell(
            command=None,
            block=False,
            detached=True,
            start_new_session=True,
            parent_environ=env,
        )

    def _launch_tool(self, suite_tool: core.SuiteTool, env=None):
        log.info(f"Launching {suite_tool.name}")
        # todo: add tool and the scope into history

        cmd = Command(
            context=suite_tool.context,
            command=suite_tool.name,  # todo: able to append args
            cwd=self._cwd or None,
            environ=env,  # todo: inject additional env
            start_new_session=suite_tool.metadata.start_new_session,
            parent=self,
        )
        # todo: connect log window if not start_new_session
        cmd.execute()


class Command(QtCore.QObject):
    stdout = QtCore.Signal(str)
    stderr = QtCore.Signal(str)
    killed = QtCore.Signal()

    def __str__(self):
        return "Command('%s')" % self.cmd

    def __init__(self,
                 context,
                 command,
                 cwd=None,
                 environ=None,
                 start_new_session=False,
                 parent=None):
        super(Command, self).__init__(parent)

        self.environ = environ
        self.context = context
        self.cwd = cwd
        self.popen = None
        self.start_new_session = start_new_session

        # `cmd` rather than `command`, to distinguish
        # between class and argument
        self.cmd = command

        self._running = False

        # Launching may take a moment, and there's no need
        # for the user to wait around for that to happen.
        thread = threading.Thread(target=self._execute)
        thread.daemon = True

        self.thread = thread

        if start_new_session and isinstance(parent, Controller):
            # connect signals
            pass

    @property
    def pid(self):
        if self.popen.poll is None:
            return self.popen.pid

    def execute(self):
        self.thread.start()

    def _execute(self):
        startupinfo = None
        no_console = hasattr(allzparkconfig, "__noconsole__")

        # Windows-only
        # Prevent additional windows from appearing when running
        # Allzpark without a console, e.g. via pythonw.exe.
        if no_console and hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        kwargs = {
            "command": self.cmd,
            "parent_environ": self.environ,
            "start_new_session": self.start_new_session,
            # Popen args
            "startupinfo": startupinfo,
            "encoding": util.subprocess_encoding(),
            "errors": util.unicode_decode_error_handler(),
            "universal_newlines": True,
            "cwd": self.cwd,
        }
        if not self.start_new_session:
            kwargs.update({
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
            })

        try:
            self.popen = self.context.execute_shell(block=False, **kwargs)
        except Exception as e:
            log.error(str(e))
            return

        if self.start_new_session:
            return

        for target in (self.listen_on_stdout,
                       self.listen_on_stderr):
            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()

    def is_running(self):
        # Normally, you'd be able to determine whether a Popen instance was
        # still running by querying Popen.poll() == None, but Rez may or may
        # not use `Popen(shell=True)` which throws this mechanism off. Instead,
        # we'll let an open pipe to STDOUT determine whether or not a process
        # is currently running.
        return self._running

    def listen_on_stdout(self):
        self._running = True
        for line in iter(self.popen.stdout.readline, ""):
            self.stdout.emit(line.rstrip())
        self._running = False
        self.killed.emit()

    def listen_on_stderr(self):
        for line in iter(self.popen.stderr.readline, ""):
            self.stderr.emit(line.rstrip())


class Thread(QtCore.QThread):

    def __init__(self, *args, **kwargs):
        super(Thread, self).__init__(*args, **kwargs)
        self._func = None
        self._args = None
        self._kwargs = None

    def set_job(self, func, *args, **kwargs):
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        self._func(*self._args, **self._kwargs)


# https://docs.python.org/3/howto/logging-cookbook.html#a-qt-gui-for-logging
class QtStatusBarHandler(logging.Handler):
    def __init__(self, ctrl, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ctrl = ctrl

    def emit(self, record):
        s = self.format(record)
        self._ctrl.status_message.emit(s)
