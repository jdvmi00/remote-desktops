"""Validate repository content without installing or running application code."""
import ast
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


TEXT_SUFFIXES = {".md", ".py", ".yml", ".yaml", ".sh", ".ps1", ".toml", ".json"}
TEXT_NAMES = {"LICENSE", ".gitignore", ".gitattributes"}
LINK = re.compile(r"\[[^\]\n]*\]\(([^)\n]+)\)")


def check_file(root, relative, tracked):
    path = root / relative
    if path.is_symlink():
        return [f"{relative}: tracked symlinks are not supported"]
    if not path.is_file():
        return [f"{relative}: tracked file is missing"]
    if path.suffix not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
        return []
    errors = []
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return [f"{relative}: expected UTF-8 text"]
    if "\r" in text:
        errors.append(f"{relative}: use LF line endings")
    if text and not text.endswith("\n"):
        errors.append(f"{relative}: missing final newline")
    for number, line in enumerate(text.splitlines(), 1):
        if line.rstrip() != line:
            errors.append(f"{relative}:{number}: trailing whitespace")
    if path.suffix == ".py":
        try:
            ast.parse(text, filename=str(relative))
        except SyntaxError as error:
            errors.append(f"{relative}:{error.lineno}: {error.msg}")
    if path.suffix == ".md":
        # Check inline file links; external URLs and heading anchors are not
        # fetched. Ignore fenced examples and inline code when scanning prose.
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        prose = re.sub(r"`[^`\n]+`", "", prose)
        for match in LINK.finditer(prose):
            target = match[1].strip().strip("<>")
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            destination = (path.parent / unquote(url.path)).resolve()
            try:
                name = destination.relative_to(root.resolve()).as_posix()
            except ValueError:
                errors.append(f"{relative}: link leaves repository: {target}")
                continue
            if name not in tracked or not destination.is_file():
                errors.append(f"{relative}: link is not a tracked file: {target}")
    return errors


def main():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                            capture_output=True, check=True)
    tracked = set(result.stdout.decode("utf-8").rstrip("\0").split("\0"))
    errors = [error for name in sorted(tracked)
              for error in check_file(root, name, tracked)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Repository validation passed ({len(tracked)} tracked files).")
    print("This checks repository content, not streaming or host display recovery.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
