"""Native OS access-control tests; only disposable fixtures are changed."""
import ctypes
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_security import LocalSecurityError, _WindowsPermissions, inspect_data_directory, secure_data_directory


class LocalSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "session"

    def test_protection_preserves_existing_content_and_is_repeatable(self):
        self.root.mkdir()
        profile = self.root / "browser"
        profile.mkdir()
        cookie_file = profile / "Cookies"
        cookie_file.write_bytes(b"private fixture bytes")
        result = secure_data_directory(self.root)
        self.assertEqual(result["status"], "protected")
        self.assertEqual(result["checked_entries"], 3)
        self.assertEqual(inspect_data_directory(self.root)["status"], "protected")
        self.assertEqual(secure_data_directory(self.root)["status"], "protected")
        self.assertEqual(cookie_file.read_bytes(), b"private fixture bytes")
        self.assertNotIn(self.temp.name, str(result))
        self.assertNotIn("private fixture", str(result))
        self.assertIn("not encryption", result["message"])

    def test_read_only_inspection_does_not_create_missing_directory(self):
        self.assertEqual(inspect_data_directory(self.root)["status"], "unverified")
        self.assertFalse(self.root.exists())

    def test_missing_parent_is_not_created_outside_requested_directory(self):
        with self.assertRaises(LocalSecurityError):
            secure_data_directory(self.root / "nested")
        self.assertFalse(self.root.exists())

    def test_filesystem_root_is_rejected_before_any_changes(self):
        with self.assertRaises(LocalSecurityError) as caught:
            secure_data_directory(Path(self.temp.name).anchor)
        self.assertEqual(caught.exception.code, "broad_path")

    def test_regular_file_cannot_be_used_as_data_directory(self):
        self.root.write_text("keep this", encoding="utf-8")
        with self.assertRaises(LocalSecurityError):
            secure_data_directory(self.root)
        self.assertEqual(self.root.read_text(encoding="utf-8"), "keep this")

    def test_hard_links_are_rejected_before_dacl_propagation(self):
        self.root.mkdir()
        outside = Path(self.temp.name) / "outside-secret"
        outside.write_text("do not touch", encoding="utf-8")
        try:
            os.link(outside, self.root / "alias")
        except OSError as error:
            self.skipTest(f"Hard links unavailable: {type(error).__name__}")
        with patch.object(_WindowsPermissions, "apply") as apply, self.assertRaises(LocalSecurityError) as caught:
            secure_data_directory(self.root)
        self.assertEqual(caught.exception.code, "hard_link")
        apply.assert_not_called()
        self.assertEqual(outside.read_text(encoding="utf-8"), "do not touch")

    def test_symlink_entries_and_root_are_not_followed(self):
        self.root.mkdir()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        sentinel = outside / "private"
        sentinel.write_text("unchanged", encoding="utf-8")
        link = self.root / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink creation unavailable: {type(error).__name__}")
        for target in (self.root, link, link / "nested"):
            with patch.object(_WindowsPermissions, "apply") as apply, self.assertRaises(LocalSecurityError) as caught:
                secure_data_directory(target)
            self.assertEqual(caught.exception.code, "linked_path")
            apply.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_tree_bound_fails_before_modifying_any_permissions(self):
        self.root.mkdir()
        (self.root / "first").write_text("one", encoding="utf-8")
        (self.root / "second").write_text("two", encoding="utf-8")
        with patch("local_security.MAX_ENTRIES", 2), patch.object(_WindowsPermissions, "apply") as apply:
            with self.assertRaises(LocalSecurityError) as caught:
                secure_data_directory(self.root)
        self.assertEqual(caught.exception.code, "entry_limit")
        apply.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows native ACL test")
    def test_windows_junction_is_rejected_without_changing_target(self):
        self.root.mkdir()
        outside = Path(self.temp.name) / "junction-target"
        outside.mkdir()
        sentinel = outside / "untouched"
        sentinel.write_bytes(b"keep")
        junction = self.root / "junction"
        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                                capture_output=True, timeout=10, check=False)
        if result.returncode:
            self.skipTest("Junction creation unavailable")
        for target in (self.root, junction, junction / "nested"):
            with patch.object(_WindowsPermissions, "apply") as apply, self.assertRaises(LocalSecurityError) as caught:
                secure_data_directory(target)
            self.assertEqual(caught.exception.code, "linked_path")
            apply.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertFalse((outside / "nested").exists())

    @unittest.skipUnless(os.name == "nt", "Windows native ACL test")
    def test_windows_new_descendants_inherit_only_current_user_and_system(self):
        secure_data_directory(self.root)
        profile = self.root / "new-profile"
        profile.mkdir()
        (profile / "Cookies").write_bytes(b"fixture")
        result = inspect_data_directory(self.root)
        self.assertEqual(result["status"], "protected", result)
        self.assertEqual(result["checked_entries"], 3)

    @unittest.skipUnless(os.name == "nt", "Windows native ACL test")
    def test_windows_extra_trustee_is_detected_and_replaced(self):
        self.root.mkdir()
        permissions = _WindowsPermissions()
        self.addCleanup(permissions.close)
        descriptor = ctypes.c_void_p()
        self.assertTrue(permissions.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;OICI;FA;;;WD)", 1, ctypes.byref(descriptor), None))
        try:
            present, defaulted = permissions.w.BOOL(), permissions.w.BOOL()
            dacl = ctypes.c_void_p()
            self.assertTrue(permissions.security.GetSecurityDescriptorDacl(
                descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)))
            with permissions.handle(self.root, self.root, True) as handle:
                self.assertEqual(permissions.security.SetSecurityInfo(handle, 1, 0x80000004, None, None, dacl, None), 0)
        finally:
            permissions.kernel.LocalFree(descriptor)
        self.assertEqual(inspect_data_directory(self.root)["status"], "unverified")
        self.assertEqual(secure_data_directory(self.root)["status"], "protected")
        self.assertEqual(inspect_data_directory(self.root)["status"], "protected")

    @unittest.skipIf(os.name == "nt", "POSIX mode test")
    def test_posix_existing_modes_are_restricted(self):
        self.root.mkdir(mode=0o755)
        cookie_file = self.root / "Cookies"
        cookie_file.write_bytes(b"fixture")
        cookie_file.chmod(0o644)
        self.assertEqual(inspect_data_directory(self.root)["status"], "unverified")
        secure_data_directory(self.root)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(cookie_file.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
