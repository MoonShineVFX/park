
from ._vendor.Qt5 import QtCore


class Controller(QtCore.QObject):

    def __init__(self, entrances):
        super(Controller, self).__init__(parent=None)

        self._entrances = entrances

    def setup_entrance(self, entrance):
        pass

    def enter_scope(self, scope):
        pass

    def select_tool(self, tool):
        pass

    def iter_scopes(self, recursive=False):
        pass
