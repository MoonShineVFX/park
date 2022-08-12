
import json
import logging
import traceback
from typing import List
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from ._vendor import qoverview
from .. import core, lib
from . import resources as res
from .models import (
    parse_icon,
    QSingleton,
    JsonModel,
    ToolsModel,
    HistoryToolModel,
    ResolvedPackagesModel,
    ResolvedEnvironmentModel,
    ResolvedEnvironmentProxyModel,
    ContextDataModel,
)


log = logging.getLogger("allzpark")


def _load_backends():

    def try_avalon_backend():
        from .widgets_avalon import AvalonWidget
        return AvalonWidget

    def try_sg_sync_backend():
        from .widgets_sg_sync import ShotGridSyncWidget
        return ShotGridSyncWidget

    return {
        "avalon": try_avalon_backend,
        "sg_sync": try_sg_sync_backend,
        # could be ftrack, or shotgrid, could be... (see core module)
    }


def _in_debug_mode():
    stream_handler = next(h for h in log.handlers if h.name == "stream")
    return stream_handler.level == logging.DEBUG


class ComboBox(QtWidgets.QComboBox):

    def __init__(self, *args, **kwargs):
        super(ComboBox, self).__init__(*args, **kwargs)
        delegate = QtWidgets.QStyledItemDelegate(self)
        self.setItemDelegate(delegate)
        # https://stackoverflow.com/a/21019371
        # also see `app.AppProxyStyle`


class BusyEventFilterSingleton(QtCore.QObject, metaclass=QSingleton):
    overwhelmed = QtCore.Signal(str, int)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() in (
            QtCore.QEvent.Scroll,
            QtCore.QEvent.KeyPress,
            QtCore.QEvent.KeyRelease,
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QEvent.MouseButtonDblClick,
        ):
            self.overwhelmed.emit("Not allowed at this moment.", 5000)
            return True
        return False


class BusyWidget(QtWidgets.QWidget):
    """
    Instead of toggling QWidget.setEnabled() to block user inputs and makes
    the appearance looks glitchy between short time processes, install an
    eventFilter to block keyboard and mouse events plus a busy cursor looks
    better.
    """
    _instances = []

    def __init__(self, *args, **kwargs):
        super(BusyWidget, self).__init__(*args, **kwargs)
        self._busy_works = set()
        self._entered = False
        self._filter = BusyEventFilterSingleton(self)
        self._instances.append(self)

    @classmethod
    def instances(cls):
        return cls._instances[:]

    @QtCore.Slot(str)  # noqa
    def set_overwhelmed(self, worker: str):
        if not self._busy_works:
            if self._entered:
                self._over_busy_cursor(True)
            self._block_children(True)

        self._busy_works.add(worker)

    @QtCore.Slot(str)  # noqa
    def pop_overwhelmed(self, worker: str):
        if worker in self._busy_works:
            self._busy_works.remove(worker)

        if not self._busy_works:
            if self._entered:
                self._over_busy_cursor(False)
            self._block_children(False)

    def enterEvent(self, event):
        if self._busy_works:
            self._over_busy_cursor(True)
        self._entered = True
        super(BusyWidget, self).enterEvent(event)

    def leaveEvent(self, event):
        if self._busy_works:
            self._over_busy_cursor(False)
        self._entered = False
        super(BusyWidget, self).leaveEvent(event)

    def _over_busy_cursor(self, over):
        if over:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BusyCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _block_children(self, block):

        def action(w):
            if block:
                w.installEventFilter(self._filter)
            else:
                w.removeEventFilter(self._filter)

        def iter_children(w):
            for c in w.children():
                yield c
                for gc in iter_children(c):
                    yield gc

        for child in list(iter_children(self)):
            action(child)
        action(self)


class SlidePageWidget(QtWidgets.QStackedWidget):
    """Stacked widget that nicely slides between its pages"""

    directions = {
        "left": QtCore.QPoint(-1, 0),
        "right": QtCore.QPoint(1, 0),
        "up": QtCore.QPoint(0, 1),
        "down": QtCore.QPoint(0, -1)
    }

    def slide_view(self, index, direction="right"):
        if self.currentIndex() == index:
            return

        offset_direction = self.directions.get(direction)
        if offset_direction is None:
            log.warning("BUG: invalid slide direction: {}".format(direction))
            return

        width = self.frameRect().width()
        height = self.frameRect().height()
        offset = QtCore.QPoint(
            offset_direction.x() * width,
            offset_direction.y() * height
        )

        new_page = self.widget(index)
        new_page.setGeometry(0, 0, width, height)
        curr_pos = new_page.pos()
        new_page.move(curr_pos + offset)
        new_page.show()
        new_page.raise_()

        current_page = self.currentWidget()

        b_pos = QtCore.QByteArray(b"pos")

        anim_old = QtCore.QPropertyAnimation(current_page, b_pos, self)
        anim_old.setDuration(250)
        anim_old.setStartValue(curr_pos)
        anim_old.setEndValue(curr_pos - offset)
        anim_old.setEasingCurve(QtCore.QEasingCurve.OutQuad)

        anim_new = QtCore.QPropertyAnimation(new_page, b_pos, self)
        anim_new.setDuration(250)
        anim_new.setStartValue(curr_pos + offset)
        anim_new.setEndValue(curr_pos)
        anim_new.setEasingCurve(QtCore.QEasingCurve.OutQuad)

        anim_group = QtCore.QParallelAnimationGroup(self)
        anim_group.addAnimation(anim_old)
        anim_group.addAnimation(anim_new)

        def slide_finished():
            self.setCurrentWidget(new_page)

        anim_group.finished.connect(slide_finished)
        anim_group.start()


class ScopeLineLabel(QtWidgets.QLineEdit):

    def __init__(self, placeholder="", *args, **kwargs):
        super(ScopeLineLabel, self).__init__(*args, **kwargs)
        self.setReadOnly(True)
        self.setPlaceholderText(placeholder)


class ClearCacheWidget(QtWidgets.QWidget):
    clear_clicked = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super(ClearCacheWidget, self).__init__(*args, **kwargs)
        clear_cache = QtWidgets.QPushButton()
        clear_cache.setObjectName("ClearCacheBtn")
        clear_cache.setToolTip("Refresh")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(clear_cache)
        clear_cache.clicked.connect(self.clear_clicked)


class WorkspaceWidget(BusyWidget):
    tools_requested = QtCore.Signal(core.AbstractScope)
    workspace_changed = QtCore.Signal(core.AbstractScope)
    workspace_refreshed = QtCore.Signal(core.AbstractScope, bool)
    backend_changed = QtCore.Signal(str)

    def __init__(self, *args, **kwargs):
        super(WorkspaceWidget, self).__init__(*args, **kwargs)
        self.setObjectName("WorkspaceWidget")

        void_page = QtWidgets.QWidget()
        void_text = QtWidgets.QLabel("No Available Backend")
        entrances = QtWidgets.QStackedWidget()
        backend_sel = ComboBox()

        layout = QtWidgets.QVBoxLayout(void_page)
        layout.addWidget(void_text)

        entrances.addWidget(void_page)  # index 0

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 4)
        layout.addWidget(entrances)
        layout.addWidget(backend_sel)

        backend_sel.currentTextChanged.connect(self._on_backend_changed)

        self._stack = entrances
        self._combo = backend_sel

    def _on_backend_changed(self, name):
        # possibly need to do some cleanup before/after signal emitted ?
        self.backend_changed.emit(name)

    def on_workspace_entered(self, scope):
        backend_changed = False
        if scope.upstream is None:  # is entrance object, backend changed
            index = self._combo.findText(scope.name)
            if index < 0:
                log.critical(f"Unknown root level {scope.name}.")
            # + 1 because we have a void_page underneath
            index += 1
            if index != self._stack.currentIndex():
                self._stack.setCurrentIndex(index)
                backend_changed = True

        widget = self._stack.currentWidget()
        widget.enter_workspace(scope, backend_changed)

    def on_workspace_updated(self, scopes):
        widget = self._stack.currentWidget()
        widget.update_workspace(scopes)

    def on_cache_cleared(self):
        widget = self._stack.currentWidget()
        widget.on_cache_cleared()

    def register_backends(self, names: List[str]):
        if self._stack.count() > 1:
            return

        possible_backends = _load_backends()

        self.blockSignals(True)

        for name in names:
            widget_getter = possible_backends.get(name)
            if widget_getter is None:
                log.error(f"No widget for backend {name!r}.")
                continue

            try:
                widget_cls = widget_getter()
            except Exception as e:
                log.error(f"Failed to get widget for backend {name!r}: {str(e)}")
                continue

            w_icon = getattr(widget_cls, "icon_path", ":/icons/server.svg")
            widget = widget_cls()
            # these four signals and slots are the essentials
            widget.tools_requested.connect(self.tools_requested.emit)
            widget.workspace_changed.connect(self.workspace_changed.emit)
            widget.workspace_refreshed.connect(self.workspace_refreshed.emit)
            assert callable(widget.enter_workspace)
            assert callable(widget.update_workspace)
            assert callable(widget.on_cache_cleared)

            self._stack.addWidget(widget)
            self._combo.addItem(QtGui.QIcon(w_icon), name)

        self.blockSignals(False)

        if self._combo.count():
            self._on_backend_changed(self._combo.currentText())
        else:
            log.error("No valid backend registered.")


class ToolsView(QtWidgets.QWidget):
    tool_cleared = QtCore.Signal()
    tool_selected = QtCore.Signal(core.SuiteTool)
    tool_launched = QtCore.Signal(core.SuiteTool)

    def __init__(self, *args, **kwargs):
        super(ToolsView, self).__init__(*args, **kwargs)
        self.setObjectName("ToolsView")

        model = ToolsModel()
        view = QtWidgets.QListView()
        view.setModel(model)
        selection = view.selectionModel()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(view)

        selection.selectionChanged.connect(self._on_selection_changed)
        view.doubleClicked.connect(self._on_double_clicked)

        self._view = view
        self._model = model

    def _on_selection_changed(self, selected, _):
        indexes = selected.indexes()
        if indexes and indexes[0].isValid():
            index = indexes[0]  # SingleSelection view
            tool = index.data(self._model.ToolRole)
            self.tool_selected.emit(tool)
        else:
            self.tool_cleared.emit()

    def _on_double_clicked(self, index):
        if index.isValid():
            tool = index.data(self._model.ToolRole)
            self.tool_launched.emit(tool)

    def on_tools_updated(self, tools):
        self._model.update_tools(tools)

    def on_cache_cleared(self):
        self._view.clearSelection()


class WorkHistoryWidget(QtWidgets.QWidget):
    MAX_ENTRY_COUNT = 20
    tool_cleared = QtCore.Signal()
    tool_selected = QtCore.Signal(core.SuiteTool)
    tool_launched = QtCore.Signal(core.SuiteTool)
    history_saved = QtCore.Signal(list)  # list of dict

    def __init__(self, *args, **kwargs):
        super(WorkHistoryWidget, self).__init__(*args, **kwargs)
        self.setObjectName("WorkHistoryWidget")

        model = HistoryToolModel()
        view = TreeView()
        view.setModel(model)
        view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        selection = view.selectionModel()
        header = view.header()
        header.setSectionResizeMode(0, header.ResizeToContents)
        header.setSectionResizeMode(1, header.Stretch)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(view)

        selection.selectionChanged.connect(self._on_selection_changed)
        view.doubleClicked.connect(self._on_double_clicked)

        self._view = view
        self._model = model
        self._history = []
        self._tools = []

    @QtCore.Slot(list, list)  # noqa
    def on_history_updated(self, history, tools):
        self._model.update_tools(tools)
        self._tools = tools
        self._history = history

    @QtCore.Slot(core.SuiteTool)  # noqa
    def on_history_made(self, tool: core.SuiteTool):
        log.debug(f"Generating scope breadcrumb: {tool.scope}")
        try:
            breadcrumb = core.generate_tool_breadcrumb(tool)
        except Exception as e:
            log.error(traceback.format_exc())
            log.error(f"Generating scope breadcrumb failed: {str(e)}")
            return

        if not breadcrumb:
            log.debug(f"No scope breadcrumb for memorizing {tool.alias!r}: "
                      f"{tool.scope}")
            return

        history = self._history
        tools = self._tools

        if breadcrumb in history:
            _tool = tools[history.index(breadcrumb)]
            tools.remove(_tool)
            history.remove(breadcrumb)

        else:
            if len(history) >= self.MAX_ENTRY_COUNT:
                history = history[:self.MAX_ENTRY_COUNT - 1]
                tools = tools[:self.MAX_ENTRY_COUNT - 1]

        history.insert(0, breadcrumb)
        tools.insert(0, tool)

        self._model.update_tools(tools)
        self.history_saved.emit(history)

    def _on_selection_changed(self, selected, _):
        indexes = selected.indexes()
        if indexes and indexes[0].isValid():
            index = indexes[0]  # SingleSelection view
            tool = index.data(self._model.ToolRole)
            self.tool_selected.emit(tool)
        else:
            self.tool_cleared.emit()

    def _on_double_clicked(self, index):
        if index.isValid():
            tool = index.data(self._model.ToolRole)
            self.tool_launched.emit(tool)


class WorkDirWidget(QtWidgets.QWidget):

    def __init__(self, *args, **kwargs):
        super(WorkDirWidget, self).__init__(*args, **kwargs)

        line = QtWidgets.QLineEdit()
        line.setObjectName("WorkDirLineRead")
        line.setReadOnly(True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line)

        self._line = line

    def on_work_dir_obtained(self, path):
        self._line.setText(path)

    def on_work_dir_resetted(self):
        self._line.setText("")


class ToolContextWidget(QtWidgets.QWidget):
    env_hovered = QtCore.Signal(str, int)

    def __init__(self, *args, **kwargs):
        super(ToolContextWidget, self).__init__(*args, **kwargs)
        # todo:
        #   1. enable changing packages path
        #   2. enable context patching
        #   3. enable package filter
        #   4. remember context patching (by tool, scope agnostic)

        launcher = ToolLaunchWidget()
        environ = ResolvedEnvironment()
        context = ResolvedContextView()

        tabs = QtWidgets.QTabBar()
        stack = QtWidgets.QStackedWidget()
        stack.setObjectName("TabStackWidget")
        tabs.setExpanding(True)
        tabs.setDocumentMode(True)
        # QTabWidget's frame (pane border) will not be rendered if documentMode
        # is enabled, so we make our own with bar + stack with border.
        tabs.addTab("Tool")
        stack.addWidget(launcher)
        tabs.addTab("Context")
        stack.addWidget(context)
        tabs.addTab("Environ")
        stack.addWidget(environ)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(0)
        layout.addWidget(tabs)
        layout.addWidget(stack)

        tabs.currentChanged.connect(stack.setCurrentIndex)
        environ.hovered.connect(self.env_hovered.emit)

        self._launcher = launcher
        self._environ = environ
        self._context = context

        # init
        context.reset()

    @QtCore.Slot(core.SuiteTool, dict)  # noqa
    def on_tool_selected(self, suite_tool: core.SuiteTool, work_env: dict):
        error = False
        context = suite_tool.context
        try:
            env = context.get_environ()
        except Exception as e:
            log.error(f"{e.__class__.__name__}: {str(e)}")
            error = True
            env = {}

        env.update(work_env)
        self._context.load(context)
        self._launcher.set_tool(suite_tool)
        self._environ.model().load(env)
        if not error:
            self._environ.model().note(
                lib.ContextEnvInspector.inspect(context)
            )

    def on_tool_cleared(self):
        self._context.reset()
        self._environ.model().clear()
        self._launcher.reset()

    def changeEvent(self, event):
        super(ToolContextWidget, self).changeEvent(event)
        if event.type() == QtCore.QEvent.StyleChange:
            # update color when theme changed
            self._update_placeholder_color()

    def _update_placeholder_color(self):
        color = self._environ.palette().color(QtGui.QPalette.PlaceholderText)
        self._environ.model().set_placeholder_color(color)


class TreeView(qoverview.VerticalExtendedTreeView):

    def __init__(self, *args, **kwargs):
        super(TreeView, self).__init__(*args, **kwargs)
        self.setAllColumnsShowFocus(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)


class JsonView(TreeView):

    def __init__(self, parent=None):
        super(JsonView, self).__init__(parent)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.on_right_click)

    def on_right_click(self, position):
        index = self.indexAt(position)

        if not index.isValid():
            # Clicked outside any item
            return

        model_ = index.model()
        menu = QtWidgets.QMenu(self)
        copy = QtWidgets.QAction("Copy JSON", menu)
        copy_full = QtWidgets.QAction("Copy full JSON", menu)

        menu.addAction(copy)
        menu.addAction(copy_full)
        menu.addSeparator()

        def on_copy():
            text = str(model_.data(index, JsonModel.JsonRole))
            app = QtWidgets.QApplication.instance()
            app.clipboard().setText(text)

        def on_copy_full():
            if isinstance(model_, QtCore.QSortFilterProxyModel):
                data = model_.sourceModel().json()
            else:
                data = model_.json()

            text = json.dumps(data,
                              indent=4,
                              sort_keys=True,
                              ensure_ascii=False)

            app = QtWidgets.QApplication.instance()
            app.clipboard().setText(text)

        copy.triggered.connect(on_copy)
        copy_full.triggered.connect(on_copy_full)

        menu.move(QtGui.QCursor.pos())
        menu.show()


class ToolLaunchWidget(QtWidgets.QWidget):
    tool_launched = QtCore.Signal(core.SuiteTool)
    shell_launched = QtCore.Signal(core.SuiteTool)

    def __init__(self, *args, **kwargs):
        super(ToolLaunchWidget, self).__init__(*args, **kwargs)

        head = QtWidgets.QWidget()
        icon = QtWidgets.QLabel()
        label = QtWidgets.QLineEdit()
        label.setObjectName("SuiteToolLabel")
        label.setReadOnly(True)
        label.setPlaceholderText("App name")

        body = QtWidgets.QWidget()

        ctx_name = QtWidgets.QLineEdit()
        ctx_name.setReadOnly(True)
        ctx_name.setPlaceholderText("Workspace setup name")
        tool_name = QtWidgets.QLineEdit()
        tool_name.setObjectName("SuiteToolName")
        tool_name.setReadOnly(True)
        tool_name.setPlaceholderText("App command")

        _size = QtCore.QSize(res.px(24), res.px(24))
        ctx_icon = QtWidgets.QLabel()
        ctx_icon.setPixmap(QtGui.QIcon(":/icons/boxes.svg").pixmap(_size))
        tool_icon = QtWidgets.QLabel()
        tool_icon.setPixmap(QtGui.QIcon(":/icons/command.svg").pixmap(_size))

        packages = ResolvedPackages()

        launch_bar = QtWidgets.QWidget()
        launch = QtWidgets.QPushButton("Launch App")
        launch.setObjectName("ToolLaunchBtn")
        shell = QtWidgets.QPushButton()
        shell.setObjectName("ShellLaunchBtn")

        layout = QtWidgets.QHBoxLayout(head)
        layout.addWidget(icon)
        layout.addWidget(label, alignment=QtCore.Qt.AlignBottom)

        layout = QtWidgets.QHBoxLayout(launch_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(launch)
        layout.addWidget(shell)

        _c_lay = QtWidgets.QHBoxLayout()
        _c_lay.addWidget(ctx_icon)
        _c_lay.addWidget(ctx_name)
        _t_lay = QtWidgets.QHBoxLayout()
        _t_lay.addWidget(tool_icon)
        _t_lay.addWidget(tool_name)

        layout = QtWidgets.QVBoxLayout(body)
        layout.addLayout(_c_lay)
        layout.addLayout(_t_lay)
        layout.addWidget(packages)
        layout.addWidget(launch_bar)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(head)
        layout.addWidget(body)

        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._unlock_launch_btn(True))

        launch.clicked.connect(self._on_launch_tool_clicked)
        shell.clicked.connect(self._on_launch_shell_clicked)

        self._timer = timer
        self._label = label
        self._icon = icon
        self._ctx = ctx_name
        self._name = tool_name
        self._launch = launch
        self._shell = shell
        self._packages = packages
        self._tool = None

        self.reset()

    def _unlock_launch_btn(self, lock):
        self._shell.setEnabled(lock)
        self._launch.setEnabled(lock)

    def _on_launch_tool_clicked(self):
        self.tool_launched.emit(self._tool)
        self._unlock_launch_btn(False)
        self._timer.start(1000)

    def _on_launch_shell_clicked(self):
        self.shell_launched.emit(self._tool)
        self._unlock_launch_btn(False)
        self._timer.start(1000)

    def reset(self):
        icon = QtGui.QIcon(":/icons/joystick.svg")
        size = QtCore.QSize(res.px(64), res.px(64))

        self._ctx.setText("")
        self._name.setText("")
        self._label.setText("")
        self._icon.setPixmap(icon.pixmap(size))
        self._packages.model().reset()
        self._unlock_launch_btn(False)

    def set_tool(self, tool: core.SuiteTool):
        icon = parse_icon(
            tool.variant.root,
            tool.metadata.icon,
            ":/icons/joystick.svg"
        )
        size = QtCore.QSize(res.px(64), res.px(64))

        self._icon.setPixmap(icon.pixmap(size))
        self._label.setText(tool.metadata.label)
        self._ctx.setText(tool.ctx_name)
        self._name.setText(tool.name)
        self._packages.model().load(tool.context.resolved_packages)
        self._tool = tool
        self._unlock_launch_btn(True)


class ResolvedPackages(QtWidgets.QWidget):

    def __init__(self, *args, **kwargs):
        super(ResolvedPackages, self).__init__(*args, **kwargs)

        model = ResolvedPackagesModel()
        view = TreeView()
        view.setModel(model)
        view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        header = view.header()
        header.setSectionResizeMode(0, header.Stretch)
        header.setSectionResizeMode(1, header.ResizeToContents)
        header.setSectionResizeMode(2, header.Stretch)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 20, 0, 10)
        layout.addWidget(view)

        view.customContextMenuRequested.connect(self.on_right_click)

        self._view = view
        self._model = model

    def model(self):
        return self._model

    def on_right_click(self, position):
        if not _in_debug_mode():
            return

        view = self._view
        model = self._model
        index = view.indexAt(position)

        if not index.isValid():
            # Clicked outside any item
            return

        menu = QtWidgets.QMenu(view)
        openfile = QtWidgets.QAction("Open file location", menu)
        copyfile = QtWidgets.QAction("Copy file location", menu)

        menu.addAction(openfile)
        menu.addAction(copyfile)

        def on_openfile():
            file_path = model.pkg_path_from_index(index)
            if file_path:
                lib.open_file_location(file_path)
            else:
                log.error("Not a valid filesystem package.")

        def on_copyfile():
            file_path = model.pkg_path_from_index(index)
            if file_path:
                clipboard = QtWidgets.QApplication.instance().clipboard()
                clipboard.setText(file_path)
            else:
                log.error("Not a valid filesystem package.")

        openfile.triggered.connect(on_openfile)
        copyfile.triggered.connect(on_copyfile)

        menu.move(QtGui.QCursor.pos())
        menu.show()


class ResolvedEnvironment(QtWidgets.QWidget):
    hovered = QtCore.Signal(str, int)

    def __init__(self, *args, **kwargs):
        super(ResolvedEnvironment, self).__init__(*args, **kwargs)

        search = QtWidgets.QLineEdit()
        search.setPlaceholderText("Search environ var..")
        search.setClearButtonEnabled(True)
        switch = QtWidgets.QCheckBox()
        switch.setObjectName("EnvFilterSwitch")
        inverse = QtWidgets.QCheckBox("Inverse")

        model = ResolvedEnvironmentModel()
        proxy = ResolvedEnvironmentProxyModel()
        proxy.setSourceModel(model)
        view = JsonView()
        view.setModel(proxy)
        view.setTextElideMode(QtCore.Qt.ElideMiddle)
        header = view.header()
        header.setSectionResizeMode(0, header.ResizeToContents)
        header.setSectionResizeMode(1, header.Stretch)

        _layout = QtWidgets.QHBoxLayout()
        _layout.setContentsMargins(0, 0, 0, 0)
        _layout.addWidget(search, stretch=True)
        _layout.addWidget(switch)
        _layout.addWidget(inverse)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(_layout)
        layout.addWidget(view)

        view.setMouseTracking(True)
        view.entered.connect(self._on_entered)
        search.textChanged.connect(self._on_searched)
        switch.stateChanged.connect(self._on_switched)
        inverse.stateChanged.connect(self._on_inverse)

        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._deferred_search)

        self._view = view
        self._proxy = proxy
        self._model = model
        self._timer = timer
        self._search = search
        self._switch = switch

        switch.setCheckState(QtCore.Qt.Checked)

    def model(self):
        return self._model

    def leaveEvent(self, event: QtCore.QEvent):
        super(ResolvedEnvironment, self).leaveEvent(event)
        self.hovered.emit("", 0)  # clear

    def _on_entered(self, index):
        if not index.isValid():
            return
        index = self._proxy.mapToSource(index)
        column = index.column()

        if column == 0:
            self.hovered.emit("", 0)  # clear

        elif column > 0:
            parent = index.parent()
            if parent.isValid():
                key = self._model.index(parent.row(), 0).data()
            else:
                key = self._model.index(index.row(), 0).data()

            if column == 1:
                value = index.data()
                scope = self._model.index(index.row(), 2, parent).data()
            else:
                value = self._model.index(index.row(), 1, parent).data()
                scope = index.data()

            self.hovered.emit(f"{key} | {value} <- {scope}", 0)

    def _on_searched(self, _):
        self._timer.start(400)

    def _on_switched(self, state):
        if state == QtCore.Qt.Checked:
            self._switch.setText("On Key")
            self._proxy.filter_by_key()
        else:
            self._switch.setText("On Value")
            self._proxy.filter_by_value()

    def _on_inverse(self, state):
        self._proxy.inverse_filter(state)
        text = self._search.text()
        self._view.expandAll() if len(text) > 1 else self._view.collapseAll()
        self._view.reset_extension()

    def _deferred_search(self):
        # https://doc.qt.io/qt-5/qregexp.html#introduction
        text = self._search.text()
        self._proxy.setFilterRegExp(text)
        self._view.expandAll() if len(text) > 1 else self._view.collapseAll()
        self._view.reset_extension()


class ResolvedContextView(QtWidgets.QWidget):

    def __init__(self, *args, **kwargs):
        super(ResolvedContextView, self).__init__(*args, **kwargs)

        top_bar = QtWidgets.QWidget()
        top_bar.setObjectName("ButtonBelt")
        attr_toggle = QtWidgets.QPushButton()
        attr_toggle.setObjectName("ContextAttrToggle")
        attr_toggle.setCheckable(True)
        attr_toggle.setChecked(True)

        model = ContextDataModel()
        view = TreeView()
        view.setObjectName("ResolvedContextTreeView")
        view.setModel(model)
        view.setTextElideMode(QtCore.Qt.ElideMiddle)
        view.setHeaderHidden(True)

        header = view.header()
        header.setSectionResizeMode(0, header.ResizeToContents)
        header.setSectionResizeMode(1, header.Stretch)

        layout = QtWidgets.QHBoxLayout(top_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(attr_toggle, alignment=QtCore.Qt.AlignLeft)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(top_bar)
        layout.addWidget(view)

        attr_toggle.toggled.connect(self._on_attr_toggled)

        self._view = view
        self._model = model

    def _on_attr_toggled(self, show_pretty):
        self._model.on_pretty_shown(show_pretty)
        self._view.update()

    def load(self, context):
        self._model.load(context)
        self._view.reset_extension()

    def reset(self):
        self._update_placeholder_color()  # set color for new model instance
        self._model.pending()
        self._view.reset_extension()

    def changeEvent(self, event):
        super(ResolvedContextView, self).changeEvent(event)
        if event.type() == QtCore.QEvent.StyleChange:
            # update color when theme changed
            self._update_placeholder_color()

    def _update_placeholder_color(self):
        color = self._view.palette().color(QtGui.QPalette.PlaceholderText)
        self._model.set_placeholder_color(color)
