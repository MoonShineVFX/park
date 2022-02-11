
import time
import logging
import inspect
import traceback
import functools
from ._vendor.Qt5 import QtCore
from .widgets import BusyWidget
from .. import core


log = logging.getLogger("allzpark")


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
    status_message = QtCore.Signal(str)

    def __init__(self, backends):
        super(Controller, self).__init__(parent=None)

        # sending log messages to status-bar
        formatter = logging.Formatter(fmt="%(levelname)-8s %(message)s")
        handler = QtStatusBarHandler(self)
        handler.set_name("gui")
        handler.setFormatter(formatter)
        handler.setLevel(logging.INFO)
        log.addHandler(handler)

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

    @QtCore.Slot(core.AbstractScope)  # noqa
    @_defer(on_time=200)
    def on_workspace_refreshed(self, scope):
        self.update_workspace(scope)

    @QtCore.Slot(core.AbstractScope)  # noqa
    @_defer(on_time=100)
    def on_scope_tools_requested(self, scope):
        self.update_tools(scope)

    @QtCore.Slot(core.SuiteTool)  # noqa
    @_defer(on_time=50)
    def on_tool_selected(self, suite_tool: core.SuiteTool):
        self.select_tool(suite_tool)

    @QtCore.Slot(core.SuiteTool)  # noqa
    @_defer(on_time=50)
    def on_tool_launched(self, suite_tool: core.SuiteTool):
        self.launch_tool(suite_tool)

    @QtCore.Slot(core.SuiteTool)  # noqa
    @_defer(on_time=50)
    def on_shell_launched(self, suite_tool: core.SuiteTool):
        self.launch_shell(suite_tool)

    def enter_workspace(self, scope):
        self.work_dir_resetted.emit()
        # inform widget to e.g. change page
        self.workspace_entered.emit(scope)

    @_thread(name="workspace", blocks=("ProductionPage",))
    def update_workspace(self, scope):
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

        self.workspace_updated.emit(children)
        if not _error:
            log.info(f"Workspace {scope.name} updated in "
                     f"{time.time() - _start:.2f} secs.")

    @_thread(name="tools", blocks=("ProductionPage",))
    def update_tools(self, scope):
        self.work_dir_resetted.emit()
        self.tools_updated.emit(list(core.iter_tools(scope)))

    def select_tool(self, suite_tool: core.SuiteTool):
        work_dir = suite_tool.scope.obtain_workspace(suite_tool)
        self.work_dir_obtained.emit(work_dir)

    def launch_tool(self, suite_tool: core.SuiteTool):
        log.warning(f"Launching {suite_tool.name}")
        # todo: add tool and the scope into history

    def launch_shell(self, suite_tool: core.SuiteTool):
        log.warning(f"Launching {suite_tool.name} shell...")


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
