// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: Copyright (c) 2025 Andrew Wyatt (Fewtarius) & ARES Contributors

import Foundation
import Logging

/// MCP Tool for Apple Notes via AppleScript.
/// Provides search, read, and create operations for Apple Notes.
public class NotesTool: ConsolidatedMCP, @unchecked Sendable {
    public let name = "notes_operations"

    public let description = """
    Search, read, create, and organize Apple Notes using macOS AppleScript.

    OPERATIONS:
    • search - Search notes by keyword (query, optional: folder, max_results)
    • get_note - Get full content of a note (note_name, optional: folder)
    • create_note - Create a new note (title, body, optional: folder)
    • list_folders - List all note folders with note counts
    • list_notes - List notes in a folder (optional: folder, max_results)
    • append_note - Append text to an existing note (note_name, text, optional: folder)
    • create_folder - Create a note folder (folder)
    • move_notes - Move notes into a folder (note_ids, target_folder)
    • delete_folder - Delete an EMPTY folder (folder)

    ORGANIZING NOTES — always drive moves by note id, never by title:
    list_notes and search return a stable `id:` (x-coredata://…) for every
    note. Apple Notes truncates long titles with an ellipsis in some views,
    so title matching silently misses those notes; ids never do. Pass ids
    to move_notes as a comma-separated list to move a whole batch in ONE
    AppleScript call — moving notes one call at a time is what makes large
    reorganizations time out partway and leave folders half-migrated.

    delete_folder refuses a folder that still holds notes unless
    confirm_non_empty is true, so a mistargeted delete cannot take the
    notes with it. Move the notes out first, then delete the empty folder.

    Notes are returned as plain text. HTML formatting in note bodies is stripped for readability.
    """

    public var supportedOperations: [String] {
        return [
            "search", "get_note", "create_note", "list_folders", "list_notes",
            "append_note", "create_folder", "move_notes", "delete_folder"
        ]
    }

    public var parameters: [String: MCPToolParameter] {
        return [
            "operation": MCPToolParameter(
                type: .string,
                description: "Notes operation to perform",
                required: true,
                enumValues: supportedOperations
            ),
            "query": MCPToolParameter(
                type: .string,
                description: "Search query for notes",
                required: false
            ),
            "note_name": MCPToolParameter(
                type: .string,
                description: "Note title/name for get_note or append_note",
                required: false
            ),
            "title": MCPToolParameter(
                type: .string,
                description: "Title for new note",
                required: false
            ),
            "body": MCPToolParameter(
                type: .string,
                description: "Body content for new note (plain text or HTML)",
                required: false
            ),
            "text": MCPToolParameter(
                type: .string,
                description: "Text to append to an existing note",
                required: false
            ),
            "folder": MCPToolParameter(
                type: .string,
                description: "Notes folder name (defaults to default account)",
                required: false
            ),
            "max_results": MCPToolParameter(
                type: .integer,
                description: "Maximum results to return (default: 20)",
                required: false
            ),
            "note_ids": MCPToolParameter(
                type: .string,
                description: "Comma-separated note ids (x-coredata://…) to move. Ids come from list_notes/search. Prefer ids over titles: Apple Notes truncates long titles, so title matching silently skips notes.",
                required: false
            ),
            "target_folder": MCPToolParameter(
                type: .string,
                description: "Destination folder name for move_notes",
                required: false
            ),
            "confirm_non_empty": MCPToolParameter(
                type: .boolean,
                description: "Required (true) to delete a folder that still contains notes. Deleting a folder deletes the notes inside it, so this defaults to false.",
                required: false
            )
        ]
    }

    private let logger = Logger(label: "com.sam.mcp.notes")

    @MainActor
    public func initialize() async throws {
        logger.debug("NotesTool initialized")
    }

    public func validateParameters(_ parameters: [String: Any]) throws -> Bool {
        // Tolerant validation: allow operation or inferred operation from parameters
        return true
    }

    @MainActor
    public func routeOperation(
        _ operation: String,
        parameters: [String: Any],
        context: MCPExecutionContext
    ) async -> MCPToolResult {
        var op = operation.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        if op.isEmpty {
            if parameters["todoList"] != nil {
                op = "todo_ack"
            } else if parameters["query"] != nil || parameters["search"] != nil {
                op = "search"
            } else if parameters["title"] != nil && (parameters["body"] != nil || parameters["content"] != nil || parameters["text"] != nil) {
                op = "create_note"
            } else if parameters["note_name"] != nil {
                op = "get_note"
            }
        }

        switch op {
        case "search", "search_notes", "find", "find_notes", "lookup":
            return await searchNotes(parameters: parameters)
        case "get_note", "read_note", "get", "read", "fetch_note", "view_note":
            return await getNote(parameters: parameters)
        case "create_note", "write", "write_note", "new_note", "save_note", "add_note":
            if parameters["todoList"] != nil && parameters["body"] == nil && parameters["content"] == nil && parameters["text"] == nil {
                return MCPToolResult(success: true, output: MCPOutput(content: "Task plan acknowledged. Ready to execute note operations."))
            }
            return await createNote(parameters: parameters)
        case "list_folders", "folders", "list_folder", "get_folders", "all_folders":
            return await listFolders()
        case "list_notes", "notes", "list_all_notes", "get_notes", "all_notes":
            return await listNotes(parameters: parameters)
        case "append_note", "append", "add_text":
            return await appendNote(parameters: parameters)
        case "create_folder", "new_folder", "add_folder", "make_folder":
            return await createFolder(parameters: parameters)
        case "move_notes", "move", "move_note":
            return await moveNotes(parameters: parameters)
        case "delete_folder", "remove_folder", "delete":
            return await deleteFolder(parameters: parameters)
        case "todo_ack":
            return MCPToolResult(success: true, output: MCPOutput(content: "Task plan acknowledged. Ready to execute note operations."))
        default:
            if parameters["todoList"] != nil {
                return MCPToolResult(success: true, output: MCPOutput(content: "Task plan acknowledged. Ready to execute note operations."))
            }
            return operationError(operation, message: "Unknown operation '\(operation)'. Supported: list_folders, list_notes, get_note, create_note, search, append_note, create_folder, move_notes.")
        }
    }

    // MARK: - AppleScript Execution

    private func runAppleScript(_ script: String) async -> (output: String, success: Bool) {
        let process = Process()
        let outPipe = Pipe()
        let errPipe = Pipe()

        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        process.standardOutput = outPipe
        process.standardError = errPipe

        do {
            try process.run()
            process.waitUntilExit()

            let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: outData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

            if process.terminationStatus != 0 {
                let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
                let errStr = String(data: errData, encoding: .utf8) ?? ""
                logger.error("AppleScript error: \(errStr)")

                if errStr.contains("Not authorized") || errStr.contains("not allowed") {
                    return ("Apple Notes access denied. Please grant automation permission in System Settings > Privacy & Security > Automation.", false)
                }
                return ("AppleScript error: \(errStr)", false)
            }

            return (output, true)
        } catch {
            return ("Failed to run AppleScript: \(error.localizedDescription)", false)
        }
    }

    private func cleanInput(_ string: String) -> String {
        return string
            .replacingOccurrences(of: "\\u0026", with: "&")
            .replacingOccurrences(of: "\\u003c", with: "<")
            .replacingOccurrences(of: "\\u003e", with: ">")
            .replacingOccurrences(of: "\\u0022", with: "\"")
            .replacingOccurrences(of: "\\u0027", with: "'")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&quot;", with: "\"")
    }

    private func escapeAppleScript(_ string: String) -> String {
        let cleaned = cleanInput(string)
        return cleaned
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }

    private func stripHTML(_ html: String) -> String {
        // Simple HTML tag stripping for readable output
        var text = html
        // Replace common HTML entities
        text = text.replacingOccurrences(of: "&nbsp;", with: " ")
        text = text.replacingOccurrences(of: "&amp;", with: "&")
        text = text.replacingOccurrences(of: "&lt;", with: "<")
        text = text.replacingOccurrences(of: "&gt;", with: ">")
        text = text.replacingOccurrences(of: "&quot;", with: "\"")
        text = text.replacingOccurrences(of: "<br>", with: "\n")
        text = text.replacingOccurrences(of: "<br/>", with: "\n")
        text = text.replacingOccurrences(of: "<br />", with: "\n")
        text = text.replacingOccurrences(of: "</p>", with: "\n")
        text = text.replacingOccurrences(of: "</div>", with: "\n")
        text = text.replacingOccurrences(of: "</li>", with: "\n")
        // Strip remaining tags
        while let range = text.range(of: "<[^>]+>", options: .regularExpression) {
            text.replaceSubrange(range, with: "")
        }
        // Clean up extra whitespace
        while text.contains("\n\n\n") {
            text = text.replacingOccurrences(of: "\n\n\n", with: "\n\n")
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // MARK: - Operations

    @MainActor
    private func searchNotes(parameters: [String: Any]) async -> MCPToolResult {
        guard let query = (parameters["query"] ?? parameters["search"] ?? parameters["term"] ?? parameters["keyword"] ?? parameters["text"]) as? String, !query.isEmpty else {
            return MCPToolResult(success: false, output: MCPOutput(content: "Missing required parameter: query"))
        }

        let maxResults = parameters["max_results"] as? Int ?? 20
        let folder = (parameters["folder"] ?? parameters["folder_name"] ?? parameters["folderName"]) as? String
        let escapedQuery = escapeAppleScript(query.lowercased())

        var folderFilter = ""
        if let folder = folder {
            folderFilter = " of folder \"\(escapeAppleScript(folder))\""
        }

        let script = """
        tell application "Notes"
            set matchingNotes to {}
            set noteCount to 0
            repeat with n in notes\(folderFilter)
                if noteCount >= \(maxResults) then exit repeat
                set noteName to name of n
                set noteBody to plaintext of n
                if (noteName contains "\(escapedQuery)") or (noteBody contains "\(escapedQuery)") then
                    set noteDate to modification date of n
                    set end of matchingNotes to noteName & "|||" & (noteDate as string) & "|||" & (text 1 thru (min of {200, length of noteBody}) of noteBody) & "|||" & (id of n as string)
                    set noteCount to noteCount + 1
                end if
            end repeat
            set AppleScript's text item delimiters to ":::"
            return matchingNotes as string
        end tell
        """

        let (output, success) = await runAppleScript(script)

        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }

        if output.isEmpty {
            return MCPToolResult(success: true, output: MCPOutput(content: "No notes matching '\(query)'."))
        }

        let entries = output.components(separatedBy: ":::")
        var formatted = "Notes matching '\(query)' (\(entries.count) found):\n\n"

        for entry in entries {
            let parts = entry.components(separatedBy: "|||")
            if parts.count >= 3 {
                formatted += "- **\(parts[0])**\n"
                formatted += "  Modified: \(parts[1])\n"
                formatted += "  Preview: \(stripHTML(parts[2]))...\n"
                if parts.count >= 4 {
                    formatted += "  id: \(parts[3])\n"
                }
                formatted += "\n"
            } else if !entry.isEmpty {
                formatted += "- \(entry)\n\n"
            }
        }

        return MCPToolResult(success: true, output: MCPOutput(content: formatted))
    }

    @MainActor
    private func getNote(parameters: [String: Any]) async -> MCPToolResult {
        guard let noteName = (parameters["note_name"] ?? parameters["title"] ?? parameters["name"] ?? parameters["subject"]) as? String else {
            return MCPToolResult(success: false, output: MCPOutput(content: "Missing required parameter: note_name"))
        }

        let folder = (parameters["folder"] ?? parameters["folder_name"] ?? parameters["folderName"]) as? String
        let escapedName = escapeAppleScript(noteName)

        var folderFilter = ""
        if let folder = folder {
            folderFilter = " of folder \"\(escapeAppleScript(folder))\""
        }

        let script = """
        tell application "Notes"
            repeat with n in notes\(folderFilter)
                if name of n is "\(escapedName)" then
                    set noteBody to plaintext of n
                    set noteDate to modification date of n
                    set noteCreated to creation date of n
                    return name of n & "|||" & (noteCreated as string) & "|||" & (noteDate as string) & "|||" & noteBody
                end if
            end repeat
            return ""
        end tell
        """

        let (output, success) = await runAppleScript(script)

        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }

        if output.isEmpty {
            return MCPToolResult(success: false, output: MCPOutput(content: "Note '\(noteName)' not found."))
        }

        let parts = output.components(separatedBy: "|||")
        if parts.count >= 4 {
            var formatted = "**\(parts[0])**\n"
            formatted += "Created: \(parts[1])\n"
            formatted += "Modified: \(parts[2])\n\n"
            formatted += stripHTML(parts[3])
            return MCPToolResult(success: true, output: MCPOutput(content: formatted))
        }

        return MCPToolResult(success: true, output: MCPOutput(content: stripHTML(output)))
    }

    @MainActor
    private func createNote(parameters: [String: Any]) async -> MCPToolResult {
        var rawTitle = (parameters["title"] ?? parameters["note_name"] ?? parameters["name"] ?? parameters["subject"]) as? String
        guard let rawBody = (parameters["body"] ?? parameters["content"] ?? parameters["text"] ?? parameters["note_body"] ?? parameters["note_content"]) as? String else {
            return MCPToolResult(success: false, output: MCPOutput(content: "Missing required parameter: body"))
        }

        // If title was not provided explicitly, infer it from the first markdown heading or line of body
        if rawTitle == nil || rawTitle?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == true {
            let lines = rawBody.components(separatedBy: .newlines)
            for line in lines {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trimmed.isEmpty {
                    rawTitle = trimmed.replacingOccurrences(of: "^#+\\s*", with: "", options: .regularExpression)
                    break
                }
            }
        }

        let title = rawTitle?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false ? rawTitle! : "Untitled Note"
        let folder = (parameters["folder"] ?? parameters["folder_name"] ?? parameters["folderName"]) as? String
        let escapedTitle = escapeAppleScript(title)
        let escapedBody = escapeAppleScript(rawBody)

        let htmlBody = "<h1>\(escapedTitle)</h1><br>\(escapedBody.replacingOccurrences(of: "\n", with: "<br>"))"

        let folderTarget: String
        if let folder = folder, !folder.isEmpty {
            folderTarget = "folder \"\(escapeAppleScript(folder))\""
        } else {
            folderTarget = "default account"
        }

        let script = """
        tell application "Notes"
            try
                make new note at \(folderTarget) with properties {name:"\(escapedTitle)", body:"\(htmlBody)"}
                return "ok"
            on error
                make new note with properties {name:"\(escapedTitle)", body:"\(htmlBody)"}
                return "ok"
            end try
        end tell
        """

        let (output, success) = await runAppleScript(script)

        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }

        logger.info("Created note: \(title)")
        return MCPToolResult(success: true, output: MCPOutput(content: "Created note '\(title)'."))
    }

    @MainActor
    private func listFolders() async -> MCPToolResult {
        let script = """
        tell application "Notes"
            set folderList to {}
            repeat with f in folders
                set end of folderList to name of f & "|||" & ((count of notes of f) as string)
            end repeat
            set AppleScript's text item delimiters to ":::"
            return folderList as string
        end tell
        """

        let (output, success) = await runAppleScript(script)

        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }

        if output.isEmpty {
            return MCPToolResult(success: true, output: MCPOutput(content: "No note folders found."))
        }

        let folders = output.components(separatedBy: ":::")
        var formatted = "Note Folders (\(folders.count)):\n\n"
        for folder in folders {
            let parts = folder.components(separatedBy: "|||")
            if parts.count >= 2 {
                // The count is what makes "is this folder safe to delete?"
                // answerable without a second round trip.
                formatted += "- \(parts[0]) (\(parts[1]) notes)\n"
            } else if !folder.isEmpty {
                formatted += "- \(folder)\n"
            }
        }

        return MCPToolResult(success: true, output: MCPOutput(content: formatted))
    }

    @MainActor
    private func listNotes(parameters: [String: Any]) async -> MCPToolResult {
        let maxResults = parameters["max_results"] as? Int ?? 20
        let folder = (parameters["folder"] ?? parameters["folder_name"] ?? parameters["folderName"]) as? String

        var folderFilter = ""
        if let folder = folder {
            folderFilter = " of folder \"\(escapeAppleScript(folder))\""
        }

        let script = """
        tell application "Notes"
            set noteList to {}
            set noteCount to 0
            repeat with n in notes\(folderFilter)
                if noteCount >= \(maxResults) then exit repeat
                set noteDate to modification date of n
                set end of noteList to name of n & "|||" & (noteDate as string) & "|||" & (id of n as string)
                set noteCount to noteCount + 1
            end repeat
            set AppleScript's text item delimiters to ":::"
            return noteList as string
        end tell
        """

        let (output, success) = await runAppleScript(script)

        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }

        if output.isEmpty {
            let scope = folder.map { " in '\($0)'" } ?? ""
            return MCPToolResult(success: true, output: MCPOutput(content: "No notes found\(scope)."))
        }

        let entries = output.components(separatedBy: ":::")
        let scope = folder.map { " in '\($0)'" } ?? ""
        var formatted = "Notes\(scope) (\(entries.count) shown):\n\n"

        for entry in entries {
            let parts = entry.components(separatedBy: "|||")
            if parts.count >= 3 {
                // The id is what move_notes consumes — emit it for every row so
                // a reorganization never has to fall back to title matching.
                formatted += "- **\(parts[0])** (modified: \(parts[1]))\n  id: \(parts[2])\n"
            } else if parts.count >= 2 {
                formatted += "- **\(parts[0])** (modified: \(parts[1]))\n"
            } else if !entry.isEmpty {
                formatted += "- \(entry)\n"
            }
        }

        return MCPToolResult(success: true, output: MCPOutput(content: formatted))
    }

    @MainActor
    private func createFolder(parameters: [String: Any]) async -> MCPToolResult {
        guard let folder = (parameters["folder"] ?? parameters["folder_name"] ?? parameters["name"]) as? String, !folder.isEmpty else {
            return MCPToolResult(success: false, output: MCPOutput(content: "Missing required parameter: folder"))
        }
        let escaped = escapeAppleScript(folder)
        let script = """
        tell application "Notes"
            if (count of (folders whose name is "\(escaped)")) > 0 then
                return "EXISTS"
            end if
            make new folder with properties {name:"\(escaped)"}
            return "CREATED"
        end tell
        """

        let (output, success) = await runAppleScript(script)
        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }
        if output == "EXISTS" {
            return MCPToolResult(success: true, output: MCPOutput(content: "Folder '\(folder)' already exists."))
        }
        return MCPToolResult(success: true, output: MCPOutput(content: "Created folder '\(folder)'."))
    }

    /// Move notes into ``target_folder`` by id, in one AppleScript call.
    ///
    /// Ids rather than titles because Apple Notes truncates long titles with
    /// an ellipsis, so a title-matched move silently skips exactly the notes
    /// whose names are longest. One call rather than one call per note
    /// because each osascript invocation pays Notes' scripting-bridge
    /// startup cost; a per-note loop over a large folder is what runs long
    /// enough to hit a tool timeout and leave a reorganization half-applied.
    ///
    /// Reports per-note outcomes instead of failing the whole batch on the
    /// first bad id, so a partial move is visible and resumable rather than
    /// silently partial.
    @MainActor
    private func moveNotes(parameters: [String: Any]) async -> MCPToolResult {
        guard let target = (parameters["target_folder"] ?? parameters["folder"] ?? parameters["destination"]) as? String, !target.isEmpty else {
            return MCPToolResult(success: false, output: MCPOutput(content: "Missing required parameter: target_folder"))
        }
        let rawIds = ((parameters["note_ids"] ?? parameters["ids"] ?? parameters["note_id"] ?? parameters["id"]) as? String) ?? ""
        let ids = rawIds
            .components(separatedBy: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard !ids.isEmpty else {
            return MCPToolResult(
                success: false,
                output: MCPOutput(content: "Missing required parameter: note_ids (comma-separated ids from list_notes/search)")
            )
        }

        let escapedTarget = escapeAppleScript(target)
        let idList = ids.map { "\"\(escapeAppleScript($0))\"" }.joined(separator: ", ")
        let script = """
        tell application "Notes"
            set targetMatches to folders whose name is "\(escapedTarget)"
            if (count of targetMatches) is 0 then
                return "NOFOLDER"
            end if
            set destFolder to item 1 of targetMatches
            set movedCount to 0
            set failedIds to {}
            repeat with rawId in {\(idList)}
                try
                    move (note id (rawId as string)) to destFolder
                    set movedCount to movedCount + 1
                on error
                    set end of failedIds to (rawId as string)
                end try
            end repeat
            set AppleScript's text item delimiters to ":::"
            return (movedCount as string) & "|||" & (failedIds as string)
        end tell
        """

        let (output, success) = await runAppleScript(script)
        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }
        if output == "NOFOLDER" {
            return MCPToolResult(
                success: false,
                output: MCPOutput(content: "Target folder '\(target)' does not exist. Create it first with create_folder.")
            )
        }

        let parts = output.components(separatedBy: "|||")
        let moved = Int(parts.first ?? "") ?? 0
        let failed = parts.count > 1
            ? parts[1].components(separatedBy: ":::").filter { !$0.isEmpty }
            : []

        var formatted = "Moved \(moved) of \(ids.count) note(s) into '\(target)'.\n"
        if !failed.isEmpty {
            formatted += "\nFailed (\(failed.count)) — id not found or not movable:\n"
            for id in failed {
                formatted += "- \(id)\n"
            }
        }
        return MCPToolResult(success: failed.isEmpty, output: MCPOutput(content: formatted))
    }

    /// Delete a folder, refusing a non-empty one unless explicitly confirmed.
    ///
    /// Deleting a Notes folder deletes the notes inside it. The default is
    /// therefore empty-only: the safe cleanup order is move the notes out,
    /// verify, then delete the now-empty folder.
    @MainActor
    private func deleteFolder(parameters: [String: Any]) async -> MCPToolResult {
        guard let folder = (parameters["folder"] ?? parameters["folder_name"] ?? parameters["name"]) as? String, !folder.isEmpty else {
            return MCPToolResult(success: false, output: MCPOutput(content: "Missing required parameter: folder"))
        }
        let confirmNonEmpty = (parameters["confirm_non_empty"] as? Bool) ?? false
        let escaped = escapeAppleScript(folder)
        let script = """
        tell application "Notes"
            set matches to folders whose name is "\(escaped)"
            if (count of matches) is 0 then
                return "NOFOLDER"
            end if
            set f to item 1 of matches
            set n to count of notes of f
            if n > 0 and not \(confirmNonEmpty ? "true" : "false") then
                return "NONEMPTY|||" & (n as string)
            end if
            delete f
            return "DELETED|||" & (n as string)
        end tell
        """

        let (output, success) = await runAppleScript(script)
        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }
        if output == "NOFOLDER" {
            return MCPToolResult(success: false, output: MCPOutput(content: "Folder '\(folder)' does not exist."))
        }

        let parts = output.components(separatedBy: "|||")
        let count = parts.count > 1 ? (Int(parts[1]) ?? 0) : 0
        if parts.first == "NONEMPTY" {
            return MCPToolResult(
                success: false,
                output: MCPOutput(content: """
                Refusing to delete '\(folder)': it still contains \(count) note(s), and deleting a \
                folder deletes the notes inside it. Move those notes out with move_notes first, then \
                delete the empty folder. To delete the folder AND its notes anyway, pass \
                confirm_non_empty: true.
                """)
            )
        }
        let suffix = count > 0 ? " (and \(count) note(s) inside it)" : ""
        return MCPToolResult(success: true, output: MCPOutput(content: "Deleted folder '\(folder)'\(suffix)."))
    }

    @MainActor
    private func appendNote(parameters: [String: Any]) async -> MCPToolResult {
        guard let noteName = (parameters["note_name"] ?? parameters["title"] ?? parameters["name"] ?? parameters["subject"]) as? String else {
            return MCPToolResult(success: false, output: MCPOutput(content: "Missing required parameter: note_name"))
        }
        guard let text = (parameters["text"] ?? parameters["body"] ?? parameters["content"] ?? parameters["note_body"]) as? String else {
            return MCPToolResult(success: false, output: MCPOutput(content: "Missing required parameter: text"))
        }

        let folder = (parameters["folder"] ?? parameters["folder_name"] ?? parameters["folderName"]) as? String
        let escapedName = escapeAppleScript(noteName)
        let escapedText = escapeAppleScript(text).replacingOccurrences(of: "\n", with: "<br>")

        var folderFilter = ""
        if let folder = folder {
            folderFilter = " of folder \"\(escapeAppleScript(folder))\""
        }

        let script = """
        tell application "Notes"
            repeat with n in notes\(folderFilter)
                if name of n is "\(escapedName)" then
                    set currentBody to body of n
                    set body of n to currentBody & "<br><br>" & "\(escapedText)"
                    return "ok"
                end if
            end repeat
            return "not_found"
        end tell
        """

        let (output, success) = await runAppleScript(script)

        if !success {
            return MCPToolResult(success: false, output: MCPOutput(content: output))
        }

        if output == "not_found" {
            return MCPToolResult(success: false, output: MCPOutput(content: "Note '\(noteName)' not found."))
        }

        logger.info("Appended to note: \(noteName)")
        return MCPToolResult(success: true, output: MCPOutput(content: "Appended text to note '\(noteName)'."))
    }
}
