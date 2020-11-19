from .vendor.Qt import QtWidgets, QtCore


class TableViewRowHover(QtWidgets.QStyledItemDelegate):

    def __init__(self, parent=None):
        super(TableViewRowHover, self).__init__(parent)
        self._hovered_row = -1

    def on_hover_updated(self, row):
        self._hovered_row = row

    def paint(self, painter, option, index):
        if index.row() == self._hovered_row:
            option.state |= QtWidgets.QStyle.State_MouseOver
        super(TableViewRowHover, self).paint(painter, option, index)


class Package(TableViewRowHover):

    editor_created = QtCore.Signal()
    editor_closed = QtCore.Signal(bool)

    def __init__(self, ctrl, parent=None):
        super(Package, self).__init__(parent)

        def on_close_editor(*args):
            self.editor_closed.emit(self._changed)
        self.closeEditor.connect(on_close_editor)

        self._changed = None
        self._default = None
        self._ctrl = ctrl

    def createEditor(self, parent, option, index):
        model = index.model()
        if index.column() != 1 or not model.data(index, "_hasVersions"):
            return

        editor = QtWidgets.QComboBox(parent)

        def on_text_activated(text):
            self._changed = text != self._default
        editor.textActivated.connect(on_text_activated)

        return editor

    def setEditorData(self, editor, index):
        model = index.model()
        options = model.data(index, "versions")
        default = index.data(QtCore.Qt.DisplayRole)

        self._changed = False
        self._default = default

        editor.addItems(options)
        editor.setCurrentIndex(options.index(default))

        self.editor_created.emit()

    def setModelData(self, editor, model, index):
        model = index.model()
        package = model.data(index, "family")
        options = model.data(index, "versions")
        default = model.data(index, "default")
        version = options[editor.currentIndex()]

        if not version or version == default:
            return

        self._ctrl.patch("%s==%s" % (package, version))
