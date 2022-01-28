
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

    def __init__(self, *args, **kwargs):
        super(ToolsModel, self).__init__(*args, **kwargs)
        self._current_tools = []

    def current_tools(self):
        return self._current_tools[:]

    def update_tools(self, tools):
        """

        :param tools:
        :type tools: list[tuple[SuiteTool, bool]]
        :return:
        """
        self.clear()

        _current_tools = []
        for tool, accepted in tools:
            _current_tools.append(tool)
            if not accepted:
                continue

            item = QtGui.QStandardItem()
            item.setText(tool.metadata.label)
            item.setIcon(parse_icon(tool.variant.root, tool.metadata.icon))
            if tool.metadata.color:
                item.setBackground(
                    QtGui.QBrush(QtGui.QColor(tool.metadata.color))
                )

            self.appendRow(item)

        self._current_tools = _current_tools
