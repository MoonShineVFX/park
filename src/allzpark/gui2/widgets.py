
import logging
from typing import List
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from .widgets_avalon import AvalonWidget
from .. import backend_avalon as avalon
from .common import (
    BusyWidget,
)


log = logging.getLogger(__name__)


entrance_widgets = {
    avalon.Entrance.backend: AvalonWidget,
    # could be ftrack, or shotgrid, could be... (see core module)
}


class WorkspaceWidget(BusyWidget):
    backend_changed = QtCore.Signal(str)

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

    def register_backends(self, names: List[str]):
        if self._stack.count() > 1:
            return

        self.blockSignals(True)

        for name in names:
            widget_cls = entrance_widgets.get(name)
            if widget_cls is None:
                log.error(f"No widget for backend {name!r}.")
                continue

            self._stack.addWidget(widget_cls())
            self._combo.addItem(
                QtGui.QIcon(widget_cls.icon_path or ":/icons/project"),
                name,
            )

        self.blockSignals(False)

        self._on_backend_changed(self._combo.currentText())
