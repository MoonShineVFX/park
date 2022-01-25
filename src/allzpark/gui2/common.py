
import logging
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets

log = logging.getLogger(__name__)

# for type hint
_SigIt = QtCore.SignalInstance


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
    overwhelmed = QtCore.Signal(str)  # type: _SigIt

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
        self._is_busy = False
        self._entered = False
        self._filter = BusyEventFilterSingleton(self)
        self._instances.append(self)

    @classmethod
    def instances(cls):
        return cls._instances[:]

    @QtCore.Slot()  # noqa
    def set_overwhelmed(self, busy):
        if self._is_busy == busy:
            return
        self._is_busy = busy
        if self._entered:
            self._over_busy_cursor(busy)
        self._block_children(busy)

    def enterEvent(self, event):
        if self._is_busy:
            self._over_busy_cursor(True)
        self._entered = True
        super(BusyWidget, self).enterEvent(event)

    def leaveEvent(self, event):
        if self._is_busy:
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


class WorkspaceBase(QtWidgets.QWidget):
    icon_path = None
    workspace_changed = QtCore.Signal(object)

    def enter_workspace(self, scope):
        raise NotImplementedError

    def get_model(self, scope):
        raise NotImplementedError


class BaseItemModel(QtGui.QStandardItemModel):
    Headers = []

    def __init__(self, *args, **kwargs):
        super(BaseItemModel, self).__init__(*args, **kwargs)
        self.setColumnCount(len(self.Headers))

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and section < len(self.Headers):
            return self.Headers[section]
        return super(BaseItemModel, self).headerData(
            section, orientation, role)

    def clear(self):
        super(BaseItemModel, self).clear()  # also clears header items, hence..
        self.setHorizontalHeaderLabels(self.Headers)


class BaseScopeModel(BaseItemModel):
    ScopeRole = QtCore.Qt.UserRole + 10
