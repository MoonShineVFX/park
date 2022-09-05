
from rez.packages import iter_packages
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets


class VersionDelegate(QtWidgets.QStyledItemDelegate):

    def createEditor(self, parent, option, index):
        editor = QtWidgets.QComboBox(parent)
        return editor

    def setEditorData(self, editor, index):
        editor.clear()

        version_name = index.data(QtCore.Qt.DisplayRole)
        package_version = index.data(QtCore.Qt.UserRole)

        package_versions = sorted(list(iter_packages(package_version.name)), key=lambda v: str(v.version))

        editor_index = 0
        for package_version in package_versions:
            label = str(package_version.version)
            editor.addItem(label, userData=package_version)

            if label == version_name:
                editor_index = editor.count() - 1

        editor.setCurrentIndex(editor_index)

    def setModelData(self, editor, model, index):
        package_version = editor.itemData(editor.currentIndex())
        if package_version:
            label = str(package_version.version)
            model.setData(index, label)
            model.setData(index, package_version, QtCore.Qt.UserRole)
