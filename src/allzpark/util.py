
import os
import json
import getpass
import logging
from contextlib import contextmanager
from functools import singledispatch, update_wrapper

log = logging.getLogger("allzpark")


def normpath(path):
    return os.path.normpath(
        os.path.normcase(os.path.abspath(os.path.expanduser(path)))
    ).replace("\\", "/")


def normpaths(*paths):
    return list(map(normpath, paths))


@contextmanager
def log_level(level, name="stream"):
    stream_handler = next(h for h in log.handlers if h.name == name)
    current = stream_handler.level
    stream_handler.setLevel(level)
    yield
    stream_handler.setLevel(current)


def elide(string, length=120):
    string = str(string)
    placeholder = "..."
    length -= len(placeholder)

    if len(string) <= length:
        return string

    half = int(length / 2)
    return string[:half] + placeholder + string[-half:]


def subprocess_encoding():
    """Codec that should be used to decode subprocess stdout/stderr

    See https://docs.python.org/3/library/codecs.html#standard-encodings

    Returns:
        str: name of codec

    """
    # nerdvegas/rez sets `encoding='utf-8'` when `universal_newlines=True` and
    # `encoding` is not in Popen kwarg.
    return "utf-8"


def unicode_decode_error_handler():
    """Error handler for handling UnicodeDecodeError in subprocess

    See https://docs.python.org/3/library/codecs.html#error-handlers

    Returns:
        str: name of registered error handler

    """
    import codecs
    import locale

    def decode_with_preferred_encoding(exception):
        # type: (UnicodeError) -> tuple[str, int]
        encoding = locale.getpreferredencoding(do_setlocale=False)
        invalid_bytes = exception.object[exception.start:]

        text = invalid_bytes.decode(encoding,
                                    # second fallback
                                    errors="backslashreplace")

        return text, len(exception.object)

    handler_name = "decode_with_preferred_encoding"
    try:
        codecs.lookup_error(handler_name)
    except LookupError:
        codecs.register_error(handler_name, decode_with_preferred_encoding)

    return handler_name


def singledispatchmethod(func):
    """A decorator like `functools.singledispatch` but for class method

    This is for Python<3.8.
    For version 3.8+, there is `functools.singledispatchmethod`.

    https://stackoverflow.com/a/24602374

    :param func:
    :return:
    """
    dispatcher = singledispatch(func)

    def wrapper(*args, **kw):
        return dispatcher.dispatch(args[1].__class__)(*args, **kw)

    wrapper.register = dispatcher.register
    update_wrapper(wrapper, func)
    return wrapper


def get_user_task():
    db = "T:/rez-studio/setup/configs/user_task.json"
    if not os.path.isfile(db):
        return ''

    with open(db, "rb") as f:
        user_docs = json.load(f)

    user = getpass.getuser().lower()
    task = user_docs.get(user, {}).get('task', '')
    return task
