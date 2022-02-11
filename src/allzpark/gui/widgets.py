
import logging
from typing import List
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from ..core import AbstractScope, SuiteTool
from .models import ToolsModel


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


class QSingleton(type(QtCore.QObject), type):
    """A metaclass for creating QObject singleton
    https://forum.qt.io/topic/88531/singleton-in-python-with-qobject
    https://bugreports.qt.io/browse/PYSIDE-1434?focusedCommentId=540135#comment-540135
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(QSingleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class BusyEventFilterSingleton(QtCore.QObject, metaclass=QSingleton):
    overwhelmed = QtCore.Signal(str)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() in (
            QtCore.QEvent.Scroll,
            QtCore.QEvent.KeyPress,
            QtCore.QEvent.KeyRelease,
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QEvent.MouseButtonDblClick,
        ):
            self.overwhelmed.emit("Not allowed at this moment.")
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


class WorkspaceWidget(BusyWidget):
    tools_requested = QtCore.Signal(AbstractScope)
    workspace_changed = QtCore.Signal(AbstractScope)
    workspace_refreshed = QtCore.Signal(AbstractScope)
    backend_changed = QtCore.Signal(str)

    def __init__(self, *args, **kwargs):
        super(WorkspaceWidget, self).__init__(*args, **kwargs)
        self.setObjectName("WorkspaceWidget")

        void_page = QtWidgets.QWidget()
        void_text = QtWidgets.QLabel("No Available Backend")
        entrances = QtWidgets.QStackedWidget()
        backend_sel = QtWidgets.QComboBox()

        layout = QtWidgets.QVBoxLayout(void_page)
        layout.addWidget(void_text)

        entrances.addWidget(void_page)  # index 0

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(entrances)
        layout.addWidget(backend_sel)

        backend_sel.currentTextChanged.connect(self._on_backend_changed)
        backend_sel.currentIndexChanged.connect(
            lambda i: entrances.setCurrentIndex(i + 1)
        )

        self._stack = entrances
        self._combo = backend_sel

    def _on_backend_changed(self, name):
        # possibly need to do some cleanup before/after signal emitted ?
        self.backend_changed.emit(name)

    def on_workspace_entered(self, scope):
        widget = self._stack.currentWidget()
        widget.enter_workspace(scope)

    def on_workspace_updated(self, scopes):
        widget = self._stack.currentWidget()
        widget.update_workspace(scopes)

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

            self._stack.addWidget(widget)
            self._combo.addItem(QtGui.QIcon(w_icon), name)

        self.blockSignals(False)

        if self._combo.count():
            self._on_backend_changed(self._combo.currentText())
        else:
            log.error("No valid backend registered.")


class WorkHistoryWidget(QtWidgets.QWidget):

    def __init__(self, *args, **kwargs):
        super(WorkHistoryWidget, self).__init__(*args, **kwargs)


class ToolsView(QtWidgets.QWidget):
    tool_selected = QtCore.Signal(SuiteTool)
    tool_launched = QtCore.Signal(SuiteTool)

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

        self._model = model

    def _on_selection_changed(self, selected, _):
        indexes = selected.indexes()
        if indexes and indexes[0].isValid():
            index = indexes[0]  # SingleSelection view
            tool = index.data(self._model.ToolRole)
            self.tool_selected.emit(tool)

    def _on_double_clicked(self, index):
        if index.isValid():
            tool = index.data(self._model.ToolRole)
            self.tool_launched.emit(tool)

    def on_tools_updated(self, tools):
        self._model.update_tools(tools)


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
    tool_launched = QtCore.Signal(SuiteTool)
    shell_launched = QtCore.Signal(SuiteTool)

    def __init__(self, *args, **kwargs):
        super(ToolContextWidget, self).__init__(*args, **kwargs)
