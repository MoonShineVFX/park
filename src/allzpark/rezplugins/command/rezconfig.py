

def suite_roots():
    """Return a dict of suite saving root path
    """
    from collections import OrderedDict as odict
    from allzpark import util
    return odict([
        ("local", util.normpath("~/rez/sweet/local")),
        ("release", util.normpath("~/rez/sweet/release")),
    ])


park = {
    # saved suite root paths
    "suite_roots": suite_roots,

}
