
import os
import sys
import logging
import signal as py_signal
from typing import Optional
from importlib import reload
from contextlib import contextmanager

from .. import core, util
from ..exceptions import BackendError
from ._vendor.Qt5 import QtCore, QtWidgets
from . import control, window, widgets, resources


if sys.platform == "darwin":
    os.environ["QT_MAC_WANTS_LAYER"] = "1"  # MacOS BigSur


log = logging.getLogger("allzpark")


def launch(app_name="park-gui"):
    """GUI entry point

    :param app_name: Application name. Used to compose the location of current
        user specific settings file. Default is "park-gui".
    :type app_name: str or None
    :return: QApplication exit code
    :rtype: int
    """
    with util.log_level(logging.INFO):
        ses = Session(app_name=app_name)
    ses.show()
    return ses.app.exec_()


class Session(object):

    def __init__(self, app_name="park-gui"):
        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])
            app.setStyle(AppProxyStyle())

            # allow user to interrupt with Ctrl+C
            def sigint_handler(signals, frame):
                sys.exit(app.exit(-1))

            py_signal.signal(py_signal.SIGINT, sigint_handler)

        # sharpen icons/images
        # * the .svg file ext is needed in file path for Qt to auto scale it.
        # * without file ext given for svg file, may need to hard-coding attr
        #   like width/height/viewBox attr in that svg file.
        # * without the Qt attr below, .svg may being rendered as they were
        #   low-res.
        app.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)

        # init

        storage = QtCore.QSettings(QtCore.QSettings.IniFormat,
                                   QtCore.QSettings.UserScope,
                                   app_name, "preferences")
        log.info("Preference file: %s" % storage.fileName())

        state = State(storage=storage)
        resources.load_themes()

        try:
            backend_entrances = core.init_backends()
        except BackendError as e:
            log.error(str(e))
            sys.exit(1)

        ctrl = control.Controller(backends=backend_entrances)
        view_ = window.MainWindow(state=state)

        # signals

        workspace = view_.find(widgets.WorkspaceWidget)
        work_dir = view_.find(widgets.WorkDirWidget)
        tool_list = view_.find(widgets.ToolsView)
        tool_context = view_.find(widgets.ToolContextWidget)
        clear_cache = view_.find(widgets.ClearCacheWidget)
        busy_filter = widgets.BusyEventFilterSingleton()

        # view -> control
        workspace.workspace_changed.connect(ctrl.on_workspace_changed)
        workspace.workspace_refreshed.connect(ctrl.on_workspace_refreshed)
        workspace.backend_changed.connect(ctrl.on_backend_changed)
        workspace.tools_requested.connect(ctrl.on_scope_tools_requested)
        clear_cache.clear_clicked.connect(ctrl.on_cache_clear_clicked)
        tool_list.tool_selected.connect(ctrl.on_tool_selected)
        tool_list.tool_launched.connect(ctrl.on_tool_launched)
        tool_context.tool_launched.connect(ctrl.on_tool_launched)
        tool_context.shell_launched.connect(ctrl.on_shell_launched)

        # control -> view
        ctrl.workspace_entered.connect(workspace.on_workspace_entered)
        ctrl.workspace_updated.connect(workspace.on_workspace_updated)
        ctrl.tools_updated.connect(tool_list.on_tools_updated)
        ctrl.work_dir_obtained.connect(work_dir.on_work_dir_obtained)
        ctrl.work_dir_resetted.connect(work_dir.on_work_dir_resetted)
        ctrl.tool_selected.connect(tool_context.on_tool_selected)

        # view -> view
        view_.dark_toggled.connect(self.on_dark_toggled)

        # status bar messages
        ctrl.status_message.connect(view_.spoken)
        busy_filter.overwhelmed.connect(view_.spoken)

        self._app = app
        self._ctrl = ctrl
        self._view = view_
        self._state = state

        # kick start
        workspace.register_backends(names=[
            name for name, _ in backend_entrances]
        )

        self.apply_theme()

    @property
    def app(self):
        return self._app

    @property
    def ctrl(self):
        return self._ctrl

    @property
    def view(self):
        return self._view

    @property
    def state(self):
        return self._state

    def on_dark_toggled(self, value):
        self._state.store_dark_mode(value)
        self.apply_theme(dark=value)
        self._view.on_status_changed(self._view.statusBar().currentMessage())

    def apply_theme(self, name=None, dark=None):
        view = self._view
        name = name or self.state.retrieve("theme")
        dark = self.state.retrieve_dark_mode() if dark is None else dark
        qss = resources.get_style_sheet(name, dark)
        view.setStyleSheet(qss)
        view.style().unpolish(view)
        view.style().polish(view)
        self.state.store("theme", resources.current_theme().name)

    def reload_theme(self):
        """For look-dev"""
        reload(resources)
        resources.load_themes()
        self.apply_theme()

    def show(self):
        view = self._view
        view.show()

        # If the window is minimized then un-minimize it.
        if view.windowState() & QtCore.Qt.WindowMinimized:
            view.setWindowState(QtCore.Qt.WindowActive)

        view.raise_()  # for MacOS
        view.activateWindow()  # for Windows

    def process(self, events=QtCore.QEventLoop.AllEvents):
        self._app.eventDispatcher().processEvents(events)

    def close(self):
        self._app.closeAllWindows()
        self._app.quit()


class State(object):
    """Store/re-store Application status in/between sessions"""

    def __init__(self, storage):
        """
        :param storage: An QtCore.QSettings instance for save/load settings
            between sessions.
        :type storage: QtCore.QSettings
        """
        self._storage = storage

    def _f(self, value):
        # Account for poor serialisation format
        true = ["2", "1", "true", True, 1, 2]
        false = ["0", "false", False, 0]

        if value in true:
            value = True

        if value in false:
            value = False

        if value and str(value).isnumeric():
            value = float(value)

        return value

    @contextmanager
    def group(self, key):
        self._storage.beginGroup(key)
        try:
            yield
        finally:
            self._storage.endGroup()

    def is_writeable(self):
        return self._storage.isWritable()

    def store(self, key, value):
        self._storage.setValue(key, value)

    def retrieve(self, key, default=None):
        value = self._storage.value(key)
        if value is None:
            value = default
        return self._f(value)

    def retrieve_dark_mode(self):
        return bool(self.retrieve("theme.on_dark"))

    def store_dark_mode(self, value):
        self.store("theme.on_dark", bool(value))

    def retrieve_history(self):
        pass

    def store_history(self):
        pass

    def preserve_layout(self, widget, group):
        # type: (QtWidgets.QWidget, str) -> None
        if not self.is_writeable():
            # todo: prompt warning
            return

        self._storage.beginGroup(group)

        self.store("geometry", widget.saveGeometry())
        if hasattr(widget, "saveState"):
            self.store("state", widget.saveState())
        if hasattr(widget, "directory"):  # QtWidgets.QFileDialog
            self.store("directory", widget.directory())

        self._storage.endGroup()

    def restore_layout(self, widget, group, keep_geo=False):
        # type: (QtWidgets.QWidget, str, bool) -> None
        self._storage.beginGroup(group)

        keys = self._storage.allKeys()

        if not keep_geo and "geometry" in keys:
            widget.restoreGeometry(self.retrieve("geometry"))
        if "state" in keys and hasattr(widget, "restoreState"):
            widget.restoreState(self.retrieve("state"))
        if "directory" in keys and hasattr(widget, "setDirectory"):
            widget.setDirectory(self.retrieve("directory"))

        self._storage.endGroup()


class AppProxyStyle(QtWidgets.QProxyStyle):
    """For styling QComboBox
    https://stackoverflow.com/a/21019371
    """
    def styleHint(
            self,
            hint: QtWidgets.QStyle.StyleHint,
            option: Optional[QtWidgets.QStyleOption] = ...,
            widget: Optional[QtWidgets.QWidget] = ...,
            returnData: Optional[QtWidgets.QStyleHintReturn] = ...,) -> int:

        if hint == QtWidgets.QStyle.SH_ComboBox_Popup:
            return 0

        return super(AppProxyStyle, self).styleHint(
            hint, option, widget, returnData)
