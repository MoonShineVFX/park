
import logging
import functools
from ._vendor.Qt5 import QtCore
from .widgets import BusyWidget
from .. import core


log = logging.getLogger(__name__)


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
                print(f"Thread {name!r} is busy, cannot process {fn_name!r}.")
                return

            blocks_ = blocks or []
            busy_widgets = [
                w for w in BusyWidget.instances() if w.objectName() in blocks_
            ]  # type: list[BusyWidget]

            for widget in busy_widgets:
                widget.set_overwhelmed(True)

            def on_finished():
                for w in busy_widgets:
                    w.set_overwhelmed(False)
                thread.finished.disconnect(on_finished)
                print(f"Thread {name!r} finished {fn_name!r}.")

            thread.finished.connect(on_finished)

            print(f"Thread {name!r} is about to run {fn_name!r}.")
            thread.set_job(func, *args, **kwargs)
            thread.start()

        return decorated
    return decorator


class Controller(QtCore.QObject):
    workspace_entered = QtCore.Signal(core.AbstractScope)
    workspace_updated = QtCore.Signal(list)
    tools_updated = QtCore.Signal(list)

    def __init__(self, backends):
        super(Controller, self).__init__(parent=None)

        self._backend_entrances = dict(backends)
        self._timers = dict()
        self._sender = dict()
        self._thread = dict()  # type: dict[str, Thread]

    @QtCore.Slot()  # noqa
    @_defer(on_time=500)
    def on_backend_changed(self, entrance):
        scope = self._backend_entrances[entrance]
        self.enter_workspace(scope)

    @QtCore.Slot()  # noqa
    def on_workspace_changed(self, scope):
        self.enter_workspace(scope)

    @QtCore.Slot()  # noqa
    def on_scope_tools_requested(self, scope):
        self.update_tools(scope)

    @_thread(name="workspace", blocks=("WorkspaceWidget",))
    def enter_workspace(self, scope):
        # inform widget to e.g. change page
        self.workspace_entered.emit(scope)
        # crawl sub-workspaces in worker thread and send to widget
        self.workspace_updated.emit(list(scope.iter_children()))

    @_thread(name="suite", blocks=("ToolsView",))
    def update_tools(self, scope):
        tools = list(core.iter_tools(scope))
        self.tools_updated.emit(tools)

    def select_tool(self, tool):
        pass


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
