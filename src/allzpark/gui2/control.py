
from ._vendor.Qt5 import QtCore


class Controller(QtCore.QObject):

    def __init__(self, state):
        super(Controller, self).__init__(parent=None)
