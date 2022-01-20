
__version__ = "2.0.0"


def package_info():
    import allzpark
    return dict(
        name=allzpark.__package__,
        version=__version__,
        path=allzpark.__path__[0],
    )


def print_info():
    import sys
    info = package_info()
    py = sys.version_info
    print(info["name"],
          info["version"],
          "from", info["path"],
          "(python {x}.{y})".format(x=py.major, y=py.minor))
