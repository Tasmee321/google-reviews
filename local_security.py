"""Restrict local session files to the current OS account, without copying secrets.

This is OS access control, not encryption or protection from administrators or
malware already running as the same user. Run before opening the data directory.
"""
import ctypes
import os
import stat
from contextlib import contextmanager
from pathlib import Path

MAX_ENTRIES = 100000


class LocalSecurityError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _failure(code="permissions"):
    return LocalSecurityError(code, "Local session protection could not be verified. Close the app and check data-folder ownership and permissions before continuing.")


def _validate_entry(path):
    entry = path.lstat()
    if stat.S_ISLNK(entry.st_mode) or getattr(entry, "st_file_attributes", 0) & 0x400:
        raise _failure("linked_path")
    if not (stat.S_ISDIR(entry.st_mode) or stat.S_ISREG(entry.st_mode)):
        raise _failure("unsupported_entry")
    if stat.S_ISREG(entry.st_mode) and entry.st_nlink != 1:
        raise _failure("hard_link")
    if os.name != "nt" and entry.st_uid != os.getuid():
        raise _failure("ownership")
    return entry


def _root(path, create):
    root = Path(os.path.abspath(os.fspath(path)))
    if root.parent == root:
        raise _failure("broad_path")
    # Never resolve/follow a junction or symlink into another user's directory.
    for ancestor in reversed(root.parents):
        attributes = ancestor.lstat()
        if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & 0x400:
            raise _failure("linked_path")
    if create:
        root.mkdir(mode=0o700, exist_ok=True)
    if not stat.S_ISDIR(_validate_entry(root).st_mode):
        raise _failure("not_directory")
    return root


def _entries(root):
    pending, count = [root], 0
    while pending:
        path = pending.pop()
        metadata = _validate_entry(path)
        count += 1
        if count > MAX_ENTRIES:
            raise _failure("entry_limit")
        yield path, metadata
        if stat.S_ISDIR(metadata.st_mode):
            with os.scandir(path) as children:
                for child in children:
                    if len(pending) + count >= MAX_ENTRIES:
                        raise _failure("entry_limit")
                    pending.append(Path(child.path))


class _WindowsPermissions:
    """Scoped Win32 buffers/handles; errors never expose paths, SIDs or usernames."""
    def __init__(self):
        from ctypes import wintypes as w
        self.w = w
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.security = ctypes.WinDLL("advapi32", use_last_error=True)
        self.allocations = []
        self._bind()
        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    def _initialize(self):
        w = self.w
        self.current_sid = self._current_sid()
        self.system_sid = self._string_sid("S-1-5-18")
        sid_string = w.LPWSTR()
        if not self.security.ConvertSidToStringSidW(self.current_sid, ctypes.byref(sid_string)):
            raise _failure()
        try:
            sddl = f"D:P(A;OICI;FA;;;{sid_string.value})(A;OICI;FA;;;SY)"
        finally:
            self.kernel.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
        descriptor = ctypes.c_void_p()
        if not self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise _failure()
        self.allocations.append(descriptor)
        present, defaulted, self.dacl = w.BOOL(), w.BOOL(), ctypes.c_void_p()
        if not self.security.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(self.dacl), ctypes.byref(defaulted)) or not present.value:
            raise _failure()

    def _bind(self):
        w, pointer = self.w, ctypes.c_void_p
        declarations = [
            (self.kernel, "GetCurrentProcess", [], w.HANDLE),
            (self.kernel, "CloseHandle", [w.HANDLE], w.BOOL),
            (self.kernel, "LocalFree", [pointer], pointer),
            (self.kernel, "CreateFileW", [w.LPCWSTR, w.DWORD, w.DWORD, pointer, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            (self.kernel, "GetFinalPathNameByHandleW", [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD], w.DWORD),
            (self.kernel, "GetFileInformationByHandle", [w.HANDLE, pointer], w.BOOL),
            (self.security, "OpenProcessToken", [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL),
            (self.security, "GetTokenInformation", [w.HANDLE, ctypes.c_int, pointer, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.security, "ConvertSidToStringSidW", [pointer, ctypes.POINTER(w.LPWSTR)], w.BOOL),
            (self.security, "ConvertStringSidToSidW", [w.LPCWSTR, ctypes.POINTER(pointer)], w.BOOL),
            (self.security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", [w.LPCWSTR, w.DWORD, ctypes.POINTER(pointer), ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.security, "GetSecurityDescriptorDacl", [pointer, ctypes.POINTER(w.BOOL), ctypes.POINTER(pointer), ctypes.POINTER(w.BOOL)], w.BOOL),
            (self.security, "GetSecurityDescriptorControl", [pointer, ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.security, "GetSecurityInfo", [w.HANDLE, ctypes.c_int, w.DWORD, ctypes.POINTER(pointer), pointer, ctypes.POINTER(pointer), pointer, ctypes.POINTER(pointer)], w.DWORD),
            (self.security, "SetSecurityInfo", [w.HANDLE, ctypes.c_int, w.DWORD, pointer, pointer, pointer, pointer], w.DWORD),
            (self.security, "GetAce", [pointer, w.DWORD, ctypes.POINTER(pointer)], w.BOOL),
            (self.security, "EqualSid", [pointer, pointer], w.BOOL),
        ]
        for library, name, arguments, result in declarations:
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result

    def _current_sid(self):
        token, size = self.w.HANDLE(), self.w.DWORD()
        if not self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise _failure()
        try:
            self.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not 1 <= size.value <= 65536:
                raise _failure()
            self.token_user = ctypes.create_string_buffer(size.value)
            if not self.security.GetTokenInformation(token, 1, self.token_user, size, ctypes.byref(size)):
                raise _failure()
            return ctypes.cast(self.token_user, ctypes.POINTER(ctypes.c_void_p))[0]
        finally:
            self.kernel.CloseHandle(token)

    def _string_sid(self, value):
        sid = ctypes.c_void_p()
        if not self.security.ConvertStringSidToSidW(value, ctypes.byref(sid)):
            raise _failure()
        self.allocations.append(sid)
        return sid

    def close(self):
        for allocation in self.allocations:
            self.kernel.LocalFree(allocation)
        self.allocations.clear()

    @contextmanager
    def handle(self, path, root, modify):
        flags = 0x02000000 | 0x00200000  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT.
        access = 0x00020000 | (0x00040000 if modify else 0)  # READ_CONTROL | WRITE_DAC.
        handle = self.kernel.CreateFileW(str(path), access, 7, None, 3, flags, None)
        if handle == ctypes.c_void_p(-1).value:
            raise _failure()
        try:
            class Information(ctypes.Structure):
                _fields_ = [("attributes", self.w.DWORD), ("created", self.w.FILETIME),
                            ("accessed", self.w.FILETIME), ("written", self.w.FILETIME),
                            ("volume", self.w.DWORD), ("size_high", self.w.DWORD),
                            ("size_low", self.w.DWORD), ("links", self.w.DWORD),
                            ("index_high", self.w.DWORD), ("index_low", self.w.DWORD)]
            info = Information()
            if not self.kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
                raise _failure()
            if info.attributes & 0x400 or (not info.attributes & 0x10 and info.links != 1):
                raise _failure("linked_path")
            name = ctypes.create_unicode_buffer(32768)
            length = self.kernel.GetFinalPathNameByHandleW(handle, name, len(name), 0)
            if not 0 < length < len(name):
                raise _failure()
            final = name.value
            if final.startswith("\\\\?\\UNC\\"):
                final = "\\\\" + final[8:]
            elif final.startswith("\\\\?\\"):
                final = final[4:]
            if not Path(os.path.normcase(final)).is_relative_to(Path(os.path.normcase(str(root)))):
                raise _failure("outside_directory")
            yield handle
        finally:
            self.kernel.CloseHandle(handle)

    def verify(self, handle, directory, root=False, owner_only=False):
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if self.security.GetSecurityInfo(handle, 1, 5, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor)):
            raise _failure()
        try:
            if not owner or not self.security.EqualSid(owner, self.current_sid):
                raise _failure("ownership")
            if owner_only:
                return
            control, revision = self.w.WORD(), self.w.DWORD()
            if not self.security.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
                raise _failure()
            if root and not control.value & 0x1000:
                raise _failure("unprotected")
            if not dacl or ctypes.cast(dacl, ctypes.POINTER(self.w.WORD))[2] != 2:
                raise _failure("unprotected")
            seen = set()
            for index in range(2):
                ace = ctypes.c_void_p()
                if not self.security.GetAce(dacl, index, ctypes.byref(ace)):
                    raise _failure()
                header = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte))
                mask = ctypes.cast(ace.value + 4, ctypes.POINTER(self.w.DWORD))[0]
                sid = ctypes.c_void_p(ace.value + 8)
                if header[0] != 0 or header[1] & 0x08 or mask != 0x1F01FF:
                    raise _failure("unprotected")
                if directory and header[1] & 3 != 3:
                    raise _failure("unprotected")
                if self.security.EqualSid(sid, self.current_sid):
                    seen.add("current")
                elif self.security.EqualSid(sid, self.system_sid):
                    seen.add("system")
                else:
                    raise _failure("unprotected")
            if seen != {"current", "system"}:
                raise _failure("unprotected")
        finally:
            self.kernel.LocalFree(descriptor)

    def apply(self, handle):
        if self.security.SetSecurityInfo(handle, 1, 0x80000004, None, None, self.dacl, None):
            raise _failure()


def _protect(path, modify):
    windows = None
    try:
        root = _root(path, modify)
        windows = _WindowsPermissions() if os.name == "nt" else None
        # Validate the complete bounded tree before changing an inheritable DACL:
        # Windows can propagate a parent ACL to existing descendants itself.
        entries = list(_entries(root))
        if modify and windows:
            for entry, metadata in entries:
                with windows.handle(entry, root, False) as handle:
                    windows.verify(handle, stat.S_ISDIR(metadata.st_mode), owner_only=True)
        count = 0
        for entry, metadata in entries:
            current = _validate_entry(entry)
            if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise _failure("changed_entry")
            directory = stat.S_ISDIR(metadata.st_mode)
            if windows:
                with windows.handle(entry, root, modify) as handle:
                    if modify:
                        windows.verify(handle, directory, owner_only=True)
                        windows.apply(handle)
                    windows.verify(handle, directory, root=entry == root)
            else:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(entry, flags)
                try:
                    current = os.fstat(descriptor)
                    if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
                        raise _failure("changed_entry")
                    if current.st_uid != os.getuid() or (not directory and current.st_nlink != 1):
                        raise _failure("ownership")
                    expected = 0o700 if directory else 0o600
                    if modify:
                        os.fchmod(descriptor, expected)
                    if stat.S_IMODE(os.fstat(descriptor).st_mode) != expected:
                        raise _failure("unprotected")
                finally:
                    os.close(descriptor)
            count += 1
        return {"status": "protected", "method": "windows-dacl" if windows else "posix-permissions",
                "checked_entries": count, "message": "Local session files are restricted to this OS account. This is access control, not encryption."}
    except LocalSecurityError:
        raise
    except (OSError, ValueError, TypeError):
        raise _failure() from None
    finally:
        if windows:
            windows.close()


def secure_data_directory(path):
    """Create/protect one data directory; parent must exist. Never follows links.

    Existing files are preserved. A failure can leave a partially tightened tree;
    callers must stop startup instead of opening a browser or writing a database.
    """
    return _protect(path, True)


def inspect_data_directory(path):
    """Read-only permission diagnostics; returns no paths, account names or SIDs."""
    try:
        return _protect(path, False)
    except LocalSecurityError as error:
        return {"status": "unverified", "method": "windows-dacl" if os.name == "nt" else "posix-permissions",
                "checked_entries": 0, "code": error.code, "message": str(error)}
