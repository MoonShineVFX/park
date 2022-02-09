
from ._vendor.Qt5 import QtCore, QtWidgets
from . import widgets


class ProductionPage(QtWidgets.QWidget):

    def __init__(self, *args, **kwargs):
        super(ProductionPage, self).__init__(*args, **kwargs)

        workspace_view = widgets.WorkspaceWidget()
        tools_view = widgets.ToolsView()
        tool_context = widgets.ToolContextWidget()

        body_split = QtWidgets.QSplitter()
        body_split.addWidget(workspace_view)
        body_split.addWidget(tools_view)
        body_split.addWidget(tool_context)

        body_split.setOrientation(QtCore.Qt.Horizontal)
        body_split.setChildrenCollapsible(False)
        body_split.setContentsMargins(0, 0, 0, 0)
        body_split.setStretchFactor(0, 20)
        body_split.setStretchFactor(1, 40)
        body_split.setStretchFactor(2, 40)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(body_split)
