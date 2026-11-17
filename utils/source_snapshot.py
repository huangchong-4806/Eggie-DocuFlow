"""Read the same bytes that were previewed, using bounded memory."""
import hashlib
import tempfile
from contextlib import contextmanager
from pathlib import Path


class PreviewChanged(ValueError):
    pass


def copy_digest(source, destination=None):
    digest = hashlib.sha256()
    with Path(source).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            if destination is not None:
                destination.write(chunk)
    return digest.hexdigest()


def _copy_reviewed(source, target, review):
    try:
        digest = copy_digest(source, target)
    except FileNotFoundError as error:
        if review is None:
            raise
        raise PreviewChanged("来源文件已移走或删除，请重新预览。") from error
    if review is not None and (Path(review.source_file) != source or review.digest != digest):
        raise PreviewChanged("来源文件与预览不一致，请重新预览并确认。")
    return digest


@contextmanager
def reviewed_stream(source, review=None):
    """Avoid disk copies for small inputs when the parser accepts a stream."""
    source = Path(source).expanduser().resolve()
    with tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024) as stream:
        digest = _copy_reviewed(source, stream, review)
        stream.seek(0)
        yield stream, digest


@contextmanager
def source_snapshot(source, review=None):
    """Path-based parsers need a private file with the original name and suffix."""
    source = Path(source).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="eggie-preview-") as folder:
        copy = Path(folder) / source.name
        with copy.open("wb") as target:
            digest = _copy_reviewed(source, target, review)
        yield copy, digest
