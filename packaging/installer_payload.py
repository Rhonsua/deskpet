"""Bounded LZMS payloads using Windows' built-in Compression API (Windows 8+).

The inner archive is an ordinary, uncompressed ZIP. The wrapper consists of
magic, total size, SHA-256 and length-prefixed independent 32 MiB buffers. Keeping
the ZIP unchanged preserves Unicode names, manifests and path checks in Setup.
"""
import ctypes
import hashlib
from pathlib import Path
import struct

MAGIC = b'TYPLZMS1'
BLOCK_SIZE = 32 * 1024 * 1024
MAX_PACKED = BLOCK_SIZE + 65536
MAX_TOTAL = 8 * 1024**3


class Codec:
    def __init__(self, *, decompress=False):
        self.api = ctypes.WinDLL('cabinet.dll', use_last_error=True)
        pointer, size = ctypes.c_void_p, ctypes.c_size_t
        create = self.api.CreateDecompressor if decompress else self.api.CreateCompressor
        create.argtypes = [ctypes.c_uint32, pointer, ctypes.POINTER(pointer)]
        create.restype = ctypes.c_int
        self.handle = pointer()
        if not create(5, None, ctypes.byref(self.handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.close = self.api.CloseDecompressor if decompress else self.api.CloseCompressor
        self.close.argtypes = [pointer]
        self.close.restype = ctypes.c_int
        self.transform = self.api.Decompress if decompress else self.api.Compress
        self.transform.argtypes = [pointer, pointer, size, pointer, size, ctypes.POINTER(size)]
        self.transform.restype = ctypes.c_int
        try:
            if not decompress:
                setter = self.api.SetCompressorInformation
                setter.argtypes = [pointer, ctypes.c_int, pointer, size]
                setter.restype = ctypes.c_int
                block = ctypes.c_uint32(BLOCK_SIZE)
                if not setter(self.handle, 1, ctypes.byref(block), ctypes.sizeof(block)):
                    raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close(self.handle)
            raise

    def process(self, data, limit):
        output = ctypes.create_string_buffer(limit)
        written = ctypes.c_size_t()
        if not self.transform(self.handle, data, len(data), output, limit, ctypes.byref(written)):
            raise ctypes.WinError(ctypes.get_last_error())
        return output.raw[:written.value]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close(self.handle)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').digest()


def compress(source, destination, progress=None):
    source, destination = Path(source), Path(destination)
    total = source.stat().st_size
    if not 0 < total <= MAX_TOTAL:
        raise ValueError('Installer payload size is out of range')
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    try:
        with Codec() as codec, source.open('rb') as reader, temporary.open('wb') as writer:
            writer.write(MAGIC + struct.pack('<Q', total) + digest(source))
            copied = 0
            while data := reader.read(BLOCK_SIZE):
                packed = codec.process(data, len(data) + 65536)
                writer.write(struct.pack('<II', len(data), len(packed)))
                writer.write(packed)
                copied += len(data)
                if progress:
                    progress(copied, total)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def decompress(source, destination):
    """Build-time roundtrip check. Runtime decoder is InstallerPayload.cs."""
    destination = Path(destination)
    try:
        with Path(source).open('rb') as reader, destination.open('xb') as writer, Codec(decompress=True) as codec:
            if reader.read(8) != MAGIC:
                raise ValueError('Invalid installer payload header')
            total, = struct.unpack('<Q', reader.read(8))
            expected = reader.read(32)
            if not 0 < total <= MAX_TOTAL or len(expected) != 32:
                raise ValueError('Invalid installer payload size')
            copied, checksum = 0, hashlib.sha256()
            while copied < total:
                raw_length, packed_length = struct.unpack('<II', reader.read(8))
                if not (0 < raw_length <= min(BLOCK_SIZE, total - copied) and 0 < packed_length <= MAX_PACKED):
                    raise ValueError('Invalid installer block length')
                packed = reader.read(packed_length)
                if len(packed) != packed_length:
                    raise ValueError('Truncated installer block')
                data = codec.process(packed, raw_length)
                if len(data) != raw_length:
                    raise ValueError('Incomplete installer block')
                checksum.update(data)
                writer.write(data)
                copied += len(data)
            if reader.read(1) or checksum.digest() != expected:
                raise ValueError('Installer payload checksum mismatch')
    except BaseException:
        # Never remove a pre-existing destination after exclusive-create fails.
        if 'writer' in locals():
            destination.unlink(missing_ok=True)
        raise
