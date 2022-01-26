
import logging
from typing import List
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from .widgets_avalon import AvalonWidget
from .. import backend_avalon as avalon
from .common import BusyWidget, WorkspaceBase
from .models import ToolsModel


log = logging.getLogger(__name__)


entrance_widgets = {
    avalon.Entrance.name: AvalonWidget,
    # could be ftrack, or shotgrid, could be... (see core module)
}


class WorkspaceWidget(BusyWidget):
    workspace_changed = QtCore.Signal(object)
    backend_changed = QtCore.Signal(str)
    scope_model_switched = QtCore.Signal(object, QtCore.QAbstractItemModel)

    def __init__(self, *args, **kwargs):
        super(WorkspaceWidget, self).__init__(*args, **kwargs)
        self.setObjectName("WorkspaceWidget")

        void_page = QtWidgets.QWidget()
        void_text = QtWidgets.QLabel("there goes nothing")
        breadcrumb = BreadcrumbWidget()
        entrances = QtWidgets.QStackedWidget()
        backend_sel = QtWidgets.QComboBox()

        layout = QtWidgets.QVBoxLayout(void_page)
        layout.addWidget(void_text)

        entrances.addWidget(void_page)  # index 0

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(breadcrumb)
        layout.addWidget(entrances)
        layout.addWidget(backend_sel)

        backend_sel.currentTextChanged.connect(self._on_backend_changed)
        backend_sel.currentIndexChanged.connect(
            lambda i: entrances.setCurrentIndex(i + 1)
        )
        breadcrumb.workspace_changed.connect(self.workspace_changed.emit)

        self._bread = breadcrumb
        self._stack = entrances
        self._combo = backend_sel

    def _on_backend_changed(self, name):
        # possibly need to do some cleanup before/after signal emitted ?
        self._bread.reset()
        self.backend_changed.emit(name)

    def on_workspace_entered(self, scope):
        self._bread.set_path(scope)
        widget = self._stack.currentWidget()
        widget.enter_workspace(scope)

        model = widget.get_model(scope)
        if model is not None:
            self.scope_model_switched.emit(scope, model)

    def register_backends(self, names: List[str]):
        if self._stack.count() > 1:
            return

        self.blockSignals(True)

        for name in names:
            widget_cls = entrance_widgets.get(name)

            if widget_cls is None:
                log.error(f"No widget for backend {name!r}.")
                continue
            if not issubclass(widget_cls, WorkspaceBase):
                log.error(f"Invalid widget type {widget_cls.__name__!r}, "
                          f"must be a subclass of {WorkspaceBase.__name__!r}.")
                continue

            widget = widget_cls()
            widget.workspace_changed.connect(self.workspace_changed.emit)

            self._stack.addWidget(widget)
            self._combo.addItem(
                QtGui.QIcon(widget_cls.icon_path or ":/icons/backend.svg"),
                name,
            )

        self.blockSignals(False)

        if self._combo.count():
            self._on_backend_changed(self._combo.currentText())
        else:
            log.error("No valid backend registered.")


class BreadcrumbWidget(QtWidgets.QTabBar):
    workspace_changed = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super(BreadcrumbWidget, self).__init__(*args, **kwargs)
        self.tabBarClicked.connect(self._on_tab_clicked)

    def _on_tab_clicked(self, index):
        scope = self.tabData(index)
        self.workspace_changed.emit(scope)

    def reset(self):
        for _ in range(self.count()):
            self.removeTab(0)

    def set_path(self, scope):
        self.reset()
        while scope is not None:
            self.insertTab(0, scope.name)
            self.setTabData(0, scope)
            scope = scope.upstream


class ToolsView(QtWidgets.QWidget):
    scope_tools_requested = QtCore.Signal(object, QtCore.QAbstractItemModel)

    def __init__(self, *args, **kwargs):
        super(ToolsView, self).__init__(*args, **kwargs)

        model = ToolsModel()
        view = QtWidgets.QListView()
        view.setModel(model)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(view)

        self._model = model

    def on_workspace_entered(self, scope):
        self.scope_tools_requested.emit(scope, self._model)
