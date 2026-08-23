"""ARES AST Codebase Symbol & Repo Map Generator.

Extracts classes, methods, functions, protocols, interfaces, and types across
multi-language repositories (Python, Swift, TypeScript, JavaScript, Rust, Go)
to produce a high-density, compact structural overview of a workspace.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Excluded directories and file patterns
EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".build",
    "build",
    "dist",
    ".idea",
    ".vscode",
    "target",
    "DerivedData",
    ".pytest_cache",
    ".mypy_cache",
}

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
}


@dataclass
class SymbolNode:
    """A code symbol in a source file."""
    name: str
    kind: str  # class, function, method, struct, enum, protocol, interface, type, trait
    line: int
    signature: str = ""
    children: list[SymbolNode] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "signature": self.signature,
            "children": [c.as_dict() for c in self.children],
        }


@dataclass
class FileSymbols:
    """Symbols extracted from a single file."""
    rel_path: str
    abs_path: str
    language: str
    symbols: list[SymbolNode] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "abs_path": self.abs_path,
            "language": self.language,
            "symbols": [s.as_dict() for s in self.symbols],
        }


def _extract_python_symbols(source_text: str) -> list[SymbolNode]:
    """Parse Python source using standard library ast module."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []

    symbols: list[SymbolNode] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_sym = SymbolNode(name=node.name, kind="class", line=node.lineno)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async def " if isinstance(item, ast.AsyncFunctionDef) else "def "
                    class_sym.children.append(
                        SymbolNode(name=item.name, kind="method", line=item.lineno, signature=f"{prefix}{item.name}")
                    )
            symbols.append(class_sym)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            symbols.append(
                SymbolNode(name=node.name, kind="function", line=node.lineno, signature=f"{prefix}{node.name}")
            )

    return symbols


_SWIFT_PATTERNS = [
    (re.compile(r"^\s*(?:public\s+|private\s+|fileprivate\s+|internal\s+|open\s+|final\s+)*(class|struct|enum|protocol|actor|extension)\s+([A-Za-z0-9_]+)"), "type"),
    (re.compile(r"^\s*(?:public\s+|private\s+|fileprivate\s+|internal\s+|open\s+|override\s+|static\s+|class\s+|mutating\s+)*func\s+([A-Za-z0-9_]+)"), "func"),
]


def _extract_regex_symbols(source_text: str, language: str) -> list[SymbolNode]:
    """Fast regex-based extractor for Swift, TypeScript/JS, Rust, and Go."""
    symbols: list[SymbolNode] = []
    lines = source_text.splitlines()

    for idx, line in enumerate(lines, start=1):
        if language == "swift":
            for pat, sym_kind in _SWIFT_PATTERNS:
                m = pat.match(line)
                if m:
                    if sym_kind == "type":
                        symbols.append(SymbolNode(name=m.group(2), kind=m.group(1), line=idx))
                    else:
                        symbols.append(SymbolNode(name=m.group(1), kind="function", line=idx))
                    break

        elif language in ("typescript", "javascript"):
            # Classes, interfaces, types, functions
            m_type = re.match(r"^\s*(?:export\s+)?(?:default\s+)?(class|interface|type|enum)\s+([A-Za-z0-9_]+)", line)
            if m_type:
                symbols.append(SymbolNode(name=m_type.group(2), kind=m_type.group(1), line=idx))
                continue
            m_func = re.match(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)", line)
            if m_func:
                symbols.append(SymbolNode(name=m_func.group(1), kind="function", line=idx))
                continue
            m_const_fn = re.match(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z0-9_]+)\s*=>", line)
            if m_const_fn:
                symbols.append(SymbolNode(name=m_const_fn.group(1), kind="function", line=idx))
                continue

        elif language == "rust":
            m_type = re.match(r"^\s*(?:pub\s+)?(struct|enum|trait|impl)\s+([A-Za-z0-9_]+)", line)
            if m_type:
                symbols.append(SymbolNode(name=m_type.group(2), kind=m_type.group(1), line=idx))
                continue
            m_fn = re.match(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)", line)
            if m_fn:
                symbols.append(SymbolNode(name=m_fn.group(1), kind="function", line=idx))
                continue

        elif language == "go":
            m_type = re.match(r"^\s*type\s+([A-Za-z0-9_]+)\s+(struct|interface)", line)
            if m_type:
                symbols.append(SymbolNode(name=m_type.group(1), kind=m_type.group(2), line=idx))
                continue
            m_func = re.match(r"^\s*func\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\s*\(", line)
            if m_func:
                symbols.append(SymbolNode(name=m_func.group(1), kind="function", line=idx))
                continue

    return symbols


def extract_file_symbols(file_path: Path, workspace_root: Path) -> FileSymbols | None:
    """Extract symbol tree from a single supported file."""
    ext = file_path.suffix.lower()
    lang = SUPPORTED_EXTENSIONS.get(ext)
    if not lang:
        return None

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    if lang == "python":
        symbols = _extract_python_symbols(text)
    else:
        symbols = _extract_regex_symbols(text, lang)

    try:
        rel_path = str(file_path.relative_to(workspace_root))
    except ValueError:
        rel_path = file_path.name

    return FileSymbols(
        rel_path=rel_path,
        abs_path=str(file_path.resolve()),
        language=lang,
        symbols=symbols,
    )


def build_workspace_repomap(
    workspace_root: Path | str,
    max_files: int = 150,
) -> dict[str, Any]:
    """Scan a workspace and generate a structured AST symbol map."""
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        return {
            "workspace": str(root),
            "files": [],
            "total_symbols": 0,
            "scanned_files": 0,
            "formatted_map": "Workspace directory not found.",
        }

    file_results: list[FileSymbols] = []
    total_symbols = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Exclude vendor and hidden directories in-place
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES and not d.startswith(".")]

        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            fpath = Path(dirpath) / fn
            if fpath.suffix.lower() in SUPPORTED_EXTENSIONS:
                res = extract_file_symbols(fpath, root)
                if res and res.symbols:
                    file_results.append(res)
                    total_symbols += len(res.symbols) + sum(len(s.children) for s in res.symbols)
                    if len(file_results) >= max_files:
                        break
        if len(file_results) >= max_files:
            break

    # Format into compact text repomap
    lines: list[str] = [f"# Codebase Symbol Map: {root.name}"]
    for f in file_results:
        lines.append(f"\n## {f.rel_path}")
        for s in f.symbols:
            if s.children:
                lines.append(f"  {s.kind} {s.name}:")
                for c in s.children:
                    lines.append(f"    - {c.name} (L{c.line})")
            else:
                lines.append(f"  - {s.kind} {s.name} (L{s.line})")

    formatted_map = "\n".join(lines)

    return {
        "workspace": str(root),
        "files": [f.as_dict() for f in file_results],
        "total_symbols": total_symbols,
        "scanned_files": len(file_results),
        "formatted_map": formatted_map,
    }
