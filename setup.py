
import os
from setuptools import setup
from allzpark.version import version

# Git is required for deployment
assert len(version.split(".")) == 3, (
    "Could not compute patch version, make sure `git` is\n"
    "available and see version.py for details")

# Store version alongside package
dirname = os.path.dirname(__file__)
fname = os.path.join(dirname, "allzpark", "__version__.py")
with open(fname, "w") as f:
    f.write("version = \"%s\"\n" % version)

setup(version=version)
