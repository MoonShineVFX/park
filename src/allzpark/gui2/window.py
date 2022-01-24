
from ._vendor.Qt5 import QtCore, QtWidgets
from . import app, widgets


class MainWindow(QtWidgets.QMainWindow):

    def __init__(self, state):
        """
        :param state:
        :type state: app.State
        """
        super(MainWindow, self).__init__(flags=QtCore.Qt.Window)

        body = QtWidgets.QWidget()

        workspace_view = widgets.WorkspaceWidget()

        layout = QtWidgets.QVBoxLayout(body)
        layout.addWidget(workspace_view)

        self._body = body
        self._state = state
        self._splitters = dict()

        self.setCentralWidget(body)
        self.statusBar().show()

    @QtCore.Slot()  # noqa
    def spoken(self, message):
        self.statusBar().showMessage(message, 2000)

    def find(self, widget_cls, name=None):
        return self._body.findChild(widget_cls, name)

    def reset_layout(self):
        with self._state.group("default"):
            self._state.restore_layout(self, "mainWindow", keep_geo=True)
            for key, split in self._splitters.items():
                self._state.restore_layout(split, key)

    def showEvent(self, event):
        super(MainWindow, self).showEvent(event)

        with self._state.group("default"):  # for resetting layout
            self._state.preserve_layout(self, "mainWindow")
            for key, split in self._splitters.items():
                self._state.preserve_layout(split, key)

        with self._state.group("current"):
            self._state.restore_layout(self, "mainWindow")
            for key, split in self._splitters.items():
                self._state.restore_layout(split, key)

    def closeEvent(self, event):
        with self._state.group("current"):
            self._state.preserve_layout(self, "mainWindow")
            for key, split in self._splitters.items():
                self._state.preserve_layout(split, key)

        return super(MainWindow, self).closeEvent(event)
