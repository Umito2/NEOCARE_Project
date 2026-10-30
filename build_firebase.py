"""Build the public Firebase UI from an explicit three-file allowlist.

The application directory is never used as a Hosting upload directory. Unknown
output entries are errors, not files for this command to delete.
"""

from pathlib import Path
import os
import stat
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
PUBLIC_DIRECTORY = Path("deployment-artifacts") / "firebase-public"
API_ORIGIN = "https://umito.pythonanywhere.com"
PUBLIC_FILES = frozenset({"index.html", "assets/neocare-i18n.js", "assets/hosting-config.js"})
PUBLIC_DIRECTORIES = frozenset({"assets"})


class FirebaseBuildError(ValueError):
    """The public output cannot be built without violating its boundaries."""


def _is_link(path):
    """Include Windows junctions and other reparse points, even dangling links."""
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _check_path(path, root, *, directory):
    if _is_link(path):
        raise FirebaseBuildError(f"Links and reparse points are not allowed: {path}")
    if not path.resolve().is_relative_to(root):
        raise FirebaseBuildError(f"Path escapes the project directory: {path}")
    if path.exists() and (not path.is_dir() if directory else not path.is_file()):
        kind = "directory" if directory else "regular file"
        raise FirebaseBuildError(f"Expected a {kind}: {path}")


def validate_public_directory(root):
    """Reject unexpected content before either building or uploading the UI."""
    root = Path(root).absolute()
    if _is_link(root) or not root.is_dir():
        raise FirebaseBuildError("The project root must be an existing directory, not a link.")
    resolved_root = root.resolve()
    output = root / PUBLIC_DIRECTORY
    for path in (root / "deployment-artifacts", output, output / "assets"):
        _check_path(path, resolved_root, directory=True)
    if not output.exists():
        return output
    pending = [output]
    while pending:
        folder = pending.pop()
        for path in folder.iterdir():
            relative = path.relative_to(output).as_posix()
            if _is_link(path):
                raise FirebaseBuildError(f"Links and reparse points are not allowed: {path}")
            if path.is_dir():
                if relative not in PUBLIC_DIRECTORIES:
                    raise FirebaseBuildError(f"Unexpected public directory: {relative}")
                pending.append(path)
            elif not path.is_file() or relative not in PUBLIC_FILES:
                raise FirebaseBuildError(f"Unexpected public file: {relative}")
    return output


def _replace_file(path, content):
    """Replace only this allowlisted path without following an existing hard link."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=".neocare-build-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build(root=ROOT):
    """Build into the fixed public subtree; never accept an arbitrary output path."""
    root = Path(root).absolute()
    output = validate_public_directory(root)
    payloads = {}
    for source_name, public_name in (
        ("index.html", "index.html"),
        ("neocare-i18n.js", "assets/neocare-i18n.js"),
    ):
        source = root / source_name
        _check_path(source, root.resolve(), directory=False)
        if not source.is_file():
            raise FirebaseBuildError(f"Missing UI source: {source_name}")
        payloads[public_name] = source.read_bytes()
    payloads["assets/hosting-config.js"] = (
        f'window.NEOCARE_HOSTING_CONFIG = Object.freeze({{apiOrigin: "{API_ORIGIN}"}});\n'
    ).encode("utf-8")

    (output / "assets").mkdir(parents=True, exist_ok=True)
    # Recheck after creating the directories and before writing any content.
    validate_public_directory(root)
    for public_name, content in payloads.items():
        _replace_file(output / public_name, content)
    validate_public_directory(root)
    actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    if actual != PUBLIC_FILES:
        raise FirebaseBuildError("The public output does not match the three-file allowlist.")
    return output


def main():
    if len(sys.argv) != 1:
        print("Usage: python build_firebase.py", file=sys.stderr)
        return 2
    try:
        output = build()
    except (FirebaseBuildError, OSError) as error:
        print(f"Firebase build stopped: {error}", file=sys.stderr)
        return 1
    print(f"Firebase public directory: {output}")
    for name in sorted(PUBLIC_FILES):
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
