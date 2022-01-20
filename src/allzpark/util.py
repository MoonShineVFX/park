
import os


def normpath(path):
    return os.path.normpath(
        os.path.normcase(os.path.abspath(os.path.expanduser(path)))
    ).replace("\\", "/")


def normpaths(*paths):
    return list(map(normpath, paths))


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
