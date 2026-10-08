import os
import tempfile
import unittest

from Source_code.modules.path_security import (
    IMAGE_EXTENSIONS,
    PathValidationError,
    resolve_allowed_file,
)


class PathSecurityTest(unittest.TestCase):
    def test_allows_file_under_configured_upload_root(self):
        with tempfile.TemporaryDirectory() as upload_root:
            image_path = os.path.join(upload_root, "frame.jpg")
            with open(image_path, "wb") as handle:
                handle.write(b"fake")

            resolved = resolve_allowed_file(
                image_path,
                allowed_extensions=IMAGE_EXTENSIONS,
                upload_folder=upload_root,
            )

            self.assertEqual(os.path.normcase(str(resolved)), os.path.normcase(image_path))

    def test_rejects_file_outside_allowed_roots_before_extension_check(self):
        with tempfile.TemporaryDirectory() as upload_root, tempfile.TemporaryDirectory() as other:
            outside_path = os.path.join(other, "win.ini")
            with open(outside_path, "w", encoding="utf-8") as handle:
                handle.write("outside")

            with self.assertRaises(PathValidationError) as ctx:
                resolve_allowed_file(
                    outside_path,
                    allowed_extensions=IMAGE_EXTENSIONS,
                    upload_folder=upload_root,
                )

            self.assertEqual(ctx.exception.status_code, 403)

    def test_rejects_wrong_extension_inside_allowed_root(self):
        with tempfile.TemporaryDirectory() as upload_root:
            text_path = os.path.join(upload_root, "note.txt")
            with open(text_path, "w", encoding="utf-8") as handle:
                handle.write("not an image")

            with self.assertRaises(PathValidationError) as ctx:
                resolve_allowed_file(
                    text_path,
                    allowed_extensions=IMAGE_EXTENSIONS,
                    upload_folder=upload_root,
                )

            self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
