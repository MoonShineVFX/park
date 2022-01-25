
import logging
from typing import List
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from .widgets_avalon import AvalonWidget
from .. import backend_avalon as avalon
from .common import BusyWidget, WorkspaceBase


log = logging.getLogger(__name__)


entrance_widgets = {
    avalon.Entrance.name: AvalonWidget,
    # could be ftrack, or shotgrid, could be... (see core module)
}


class WorkspaceWidget(BusyWidget):
    workspace_changed = QtCore.Signal(object)
    backend_changed = QtCore.Signal(str)
    model_switched = QtCore.Signal(QtCore.QAbstractItemModel)

    def __init__(self, *args, **kwargs):
        super(WorkspaceWidget, self).__init__(*args, **kwargs)
        self.setObjectName("WorkspaceWidget")

        void_page = QtWidgets.QWidget()
        void_text = QtWidgets.QLabel("there goes nothing")
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

        model = widget.get_model(scope)
        if model is not None:
            self.model_switched.emit(model)

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
