import pytest
from fastapi_app.harness.linter import DiffLinter, LintReport

def test_clean_diff_passes():
    diff = """--- a/src/button.tsx
+++ b/src/button.tsx
@@ -10,3 +10,4 @@
 function Button() {
+    const handleClick = () => executeActiveAction();
     return <button onClick={handleClick}>Send</button>;
 }
"""
    report = DiffLinter.inspect_diff(diff)
    assert report.passed is True
    assert len(report.violations) == 0
    assert "PASSED" in report.summary

def test_console_log_stub_rejected():
    diff = """--- a/apps/web/src/features/chat/ConversationPage.tsx
+++ b/apps/web/src/features/chat/ConversationPage.tsx
@@ -755,3 +755,4 @@
                 onCopy={(text) => handleCopy(text)}
+                onBranch={(messageId) => console.log("Branch from message", messageId)}
                 onRetry={(messageId) => handleRetry(messageId)}
"""
    report = DiffLinter.inspect_diff(diff)
    assert report.passed is False
    assert len(report.violations) == 1
    assert report.violations[0].rule == "NO_CONSOLE_LOG_STUB"
    assert report.violations[0].file == "apps/web/src/features/chat/ConversationPage.tsx"
    assert "Unwired console.log placeholder" in report.violations[0].message

def test_todo_comment_rejected():
    diff = """--- a/src/adapter.py
+++ b/src/adapter.py
@@ -20,2 +20,3 @@
 def connect_backend():
+    # TODO: add error handling for offline socket
     return socket.connect()
"""
    report = DiffLinter.inspect_diff(diff)
    assert report.passed is False
    assert any(v.rule == "NO_TODO_COMMENT" for v in report.violations)

def test_empty_handler_rejected():
    diff = """--- a/src/menu.tsx
+++ b/src/menu.tsx
@@ -5,2 +5,3 @@
 return (
+    <button onClick={() => {}}>Close</button>
 );
"""
    report = DiffLinter.inspect_diff(diff)
    assert report.passed is False
    assert any(v.rule == "NO_EMPTY_HANDLER" for v in report.violations)

def test_python_pass_stub_rejected():
    diff = """--- a/src/service.py
+++ b/src/service.py
@@ -1,2 +1,3 @@
+def fetch_remote_records(): pass
"""
    report = DiffLinter.inspect_diff(diff)
    assert report.passed is False
    assert any(v.rule == "NO_PYTHON_PASS_STUB" for v in report.violations)

def test_python_syntax_error_detected():
    bad_code = "def broken_func(:\n    return 42"
    report = DiffLinter.inspect_python_syntax("service.py", bad_code)
    assert report.passed is False
    assert len(report.violations) == 1
    assert report.violations[0].rule == "PYTHON_SYNTAX_ERROR"
