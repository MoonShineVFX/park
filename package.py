
import subprocess
early = globals()["early"]  # lint helper


name = "allzpark"

description = "Package-based application launcher for VFX and games " \
              "production"


@early()
def version():
    return subprocess.check_output(
        ["python", "setup.py", "--version"],
        universal_newlines=True,
    ).strip()


@early()
def authors():
    name_list = subprocess.check_output(
        ["git", "shortlog", "-sn"]
    ).decode()
    return [
        n.strip().split("\t", 1)[-1]
        for n in name_list.strip().split("\n")
    ]


tools = [
    "allzpark",
    "park",  # alias of `allzpark`
]

requires = [
    "rez",
    "Qt.py",
    "python",
]

build_command = "python -c \"%s\"" % """
from os import environ
from subprocess import check_call, PIPE
i = bool('{install}')
d = environ['REZ_BUILD_INSTALL_PATH'] if i else environ['REZ_BUILD_PATH']
check_call(['python', 'setup.py', 'build', '--build-base', d], cwd=r'{root}')
""".strip().replace("\n", ";")


def commands():
    env = globals()["env"]
    alias = globals()["alias"]

    env.PYTHONPATH.prepend("{root}/lib")

    alias("allzpark", "python -m allzpark")
    alias("park", "python -m allzpark")
