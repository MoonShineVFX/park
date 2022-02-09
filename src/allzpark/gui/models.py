
import logging
from ._vendor.Qt5 import QtCore, QtGui
from ..core import SuiteTool

log = logging.getLogger("allzpark")


def parse_icon(root, template):
    try:
        fname = template.format(
            root=root,
            width=32,
            height=32,
            w=32,
            h=32
        )

    except KeyError:
        fname = ""

    return QtGui.QIcon(fname)


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
        """Clear model and header

        Removes all items (including header items) from the model and sets
        the number of rows and columns to zero.

        Note: Header view's section resize mode setting will be cleared
            altogether. Consider this action as a full reset.

        """
        super(BaseItemModel, self).clear()  # also clears header items, hence..
        self.setHorizontalHeaderLabels(self.Headers)

    def reset(self):
        """Remove all rows and set row count to zero

        This doesn't touch header.

        """
        self.removeRows(0, self.rowCount())
        self.setRowCount(0)

    def flags(self, index):
        """

        :param index:
        :type index: QtCore.QModelIndex
        :return:
        :rtype: QtCore.Qt.ItemFlags
        """
        return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable


class BaseScopeModel(BaseItemModel):
    ScopeRole = QtCore.Qt.UserRole + 10


class ToolsModel(BaseItemModel):
    Headers = ["Name"]

    def update_tools(self, tools):
        """

        :param tools:
        :type tools: list[SuiteTool]
        :return:
        """
        self.reset()

        for tool in tools:
            item = QtGui.QStandardItem()
            item.setText(tool.metadata.label)
            item.setIcon(parse_icon(tool.variant.root, tool.metadata.icon))
            if tool.metadata.color:
                item.setBackground(
                    QtGui.QBrush(QtGui.QColor(tool.metadata.color))
                )

            self.appendRow(item)
