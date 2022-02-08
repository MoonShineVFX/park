
from ._vendor.Qt5 import QtGui
from .common import BaseItemModel
from ..core import SuiteTool


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
