
if __name__ == "__main__":
    import os
    from allzpark.backend_avalon import Project, get_entrance
    from Qt5 import QtGui, QtWidgets

    _entrance = get_entrance(uri=os.environ["AVALON_MONGO"])

    app = QtWidgets.QApplication()  # must be inited before all other widgets
    dialog = QtWidgets.QDialog()
    combo = QtWidgets.QComboBox()
    model = QtGui.QStandardItemModel()
    view = QtWidgets.QTreeView()
    view.setModel(model)

    # setup model
    for project_ in _entrance.iter_children():
        if project_.is_active:
            combo.addItem(project_.name, project_)

    # layout
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(combo)
    layout.addWidget(view)

    # signal
    def update_assets(index):
        project_item = combo.itemData(index)  # type: Project
        model.clear()
        _asset_items = dict()
        for asset in project_item.iter_children():
            if not asset.is_hidden:
                item = QtGui.QStandardItem(asset.name)
                _asset_items[asset.name] = item
                if asset.is_silo:
                    model.appendRow(item)
                else:
                    parent = _asset_items[asset.parent.name]
                    parent.appendRow(item)

    combo.currentIndexChanged.connect(update_assets)

    # run
    dialog.open()
    app.exec_()
