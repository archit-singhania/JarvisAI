"""Single-use PDF worker. Receive document bytes through stdin only."""
import io
import errno
import sys
import os
import subprocess
from pathlib import Path
from threading import BoundedSemaphore


MEMORY_LIMIT = 384 * 1024 * 1024
PARSER_SLOTS = BoundedSemaphore(2)
ISOLATION_UNAVAILABLE_EXIT = 78


class PDFIsolationUnavailable(RuntimeError):
    """The configured filesystem isolation policy could not be applied."""


def limit_worker_memory():
    if os.name != 'nt':
        import resource
        _, hard_limit = resource.getrlimit(resource.RLIMIT_AS)
        limit = MEMORY_LIMIT if hard_limit == resource.RLIM_INFINITY else min(hard_limit, MEMORY_LIMIT)
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        return

    import ctypes as ct
    from ctypes import wintypes as wt

    class BasicLimits(ct.Structure):
        _fields_ = [
            ('process_time', ct.c_int64), ('job_time', ct.c_int64),
            ('flags', wt.DWORD), ('min_working_set', ct.c_size_t),
            ('max_working_set', ct.c_size_t), ('active_processes', wt.DWORD),
            ('affinity', ct.c_size_t), ('priority', wt.DWORD), ('scheduling', wt.DWORD),
        ]

    class ExtendedLimits(ct.Structure):
        _fields_ = [
            ('basic', BasicLimits), ('io_counters', ct.c_uint64 * 6),
            ('process_memory', ct.c_size_t), ('job_memory', ct.c_size_t),
            ('peak_process_memory', ct.c_size_t), ('peak_job_memory', ct.c_size_t),
        ]

    kernel = ct.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.GetCurrentProcess.restype = wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ct.WinError(ct.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x100 | 0x8  # Process memory and active process count.
    limits.basic.active_processes = 1
    limits.process_memory = MEMORY_LIMIT
    if not kernel.SetInformationJobObject(job, 9, ct.byref(limits), ct.sizeof(limits)):
        raise ct.WinError(ct.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise ct.WinError(ct.get_last_error())
    # Windows closes the job handle when this single-use worker exits.


def restrict_parser_io():
    """Reject Python-level filesystem, network and process access during parsing."""
    def audit(event, args):
        if (event == 'open' or event.startswith(('socket.', 'subprocess.', 'ctypes.', 'os.exec', 'os.spawn'))
                or event in {'os.system', 'os.listdir', 'os.scandir', 'os.chdir', 'os.remove',
                             'os.rename', 'os.mkdir', 'os.rmdir', 'os.chmod', 'os.link', 'os.symlink'}):
            raise PermissionError('PDF parsing only supports standard input and output')
    sys.addaudithook(audit)


def restrict_linux_filesystem():
    """Deny new file access in the worker on supported Linux kernels."""
    if sys.platform != 'linux' or os.uname().machine not in {'x86_64', 'aarch64'}:
        return False

    import ctypes as ct

    libc = ct.CDLL(None, use_errno=True)
    libc.syscall.restype = ct.c_long
    create_ruleset, restrict_self = 444, 446
    abi = libc.syscall(create_ruleset, None, 0, 1)  # LANDLOCK_CREATE_RULESET_VERSION
    if abi < 0:
        error = ct.get_errno()
        if error in {errno.ENOSYS, errno.EOPNOTSUPP}:
            return False
        raise OSError(error, os.strerror(error))

    # ABI 1 handles execute, read, write and directory entry operations.
    rights = (1 << 13) - 1
    if abi >= 2:
        rights |= 1 << 13  # Refer (cross-directory rename/link).
    if abi >= 3:
        rights |= 1 << 14  # Truncate.
    if abi >= 5:
        rights |= 1 << 15  # Device ioctl.
    handled = ct.c_uint64(rights)
    fd = libc.syscall(create_ruleset, ct.byref(handled), ct.sizeof(handled), 0)
    if fd < 0:
        error = ct.get_errno()
        raise OSError(error, os.strerror(error))
    try:
        # PR_SET_NO_NEW_PRIVS permits unprivileged enforcement. No paths are granted.
        if libc.prctl(38, 1, 0, 0, 0) < 0 or libc.syscall(restrict_self, fd, 0) < 0:
            error = ct.get_errno()
            raise OSError(error, os.strerror(error))
    finally:
        os.close(fd)
    return True


def extract_document(data, *, upload=False):
    mode = 'upload' if upload else 'watch'
    if not PARSER_SLOTS.acquire(timeout=10):
        raise TimeoutError('PDF workers are busy')
    try:
        result = subprocess.run(
            [sys.executable, '-I', str(Path(__file__).resolve()), mode],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=10, check=True,
            env={key: os.environ[key] for key in (
                'SystemRoot', 'TEMP', 'TMP', 'PATH', 'WEDNESDAY_REQUIRE_PDF_LANDLOCK',
            ) if key in os.environ},
        )
    except subprocess.CalledProcessError as error:
        if error.returncode == ISOLATION_UNAVAILABLE_EXIT:
            raise PDFIsolationUnavailable(
                'PDF extraction requires OS filesystem isolation on this host.'
            ) from None
        raise
    finally:
        PARSER_SLOTS.release()
    return result.stdout.decode('utf-8')


def extract(data, reader_type, byte_limit, text_limit):
    if len(data) > byte_limit:
        raise ValueError("Input exceeds extraction limit")
    reader = reader_type(io.BytesIO(data))
    if len(reader.pages) > 100:
        raise ValueError("Page limit exceeded")
    pages = []
    length = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        length += len(text) + bool(pages)
        if length > text_limit:
            raise ValueError("Text limit exceeded")
        pages.append(text)
    return "\n".join(pages)


if __name__ == "__main__":
    limit_worker_memory()
    from pypdf import PdfReader

    upload = sys.argv[1:] == ['upload']
    byte_limit = (10 if upload else 4) * 1024 * 1024
    data = sys.stdin.buffer.read(byte_limit + 1)
    requires_isolation = os.environ.get('WEDNESDAY_REQUIRE_PDF_LANDLOCK') == '1'
    try:
        isolated = restrict_linux_filesystem()
    except OSError:
        if requires_isolation:
            sys.exit(ISOLATION_UNAVAILABLE_EXIT)
        raise
    if requires_isolation and not isolated:
        sys.exit(ISOLATION_UNAVAILABLE_EXIT)
    restrict_parser_io()
    sys.stdout.buffer.write(extract(data, PdfReader, byte_limit, 2000000 if upload else 200000).encode("utf-8"))
