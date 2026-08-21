import Foundation
import XCTest
@testable import ARES

/// ARES is a menu-bar-only app. These invariants are easy to undo by accident —
/// a single `setActivationPolicy(.regular)` or a re-added `WindowGroup` puts the
/// Dock icon back and reopens a window on every launch — so they are asserted
/// against the sources and the bundle recipe directly.
final class MenuBarOnlyLifecycleTests: XCTestCase {
    private func repositoryFile(_ relativePath: String) throws -> String {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // ARESTests
            .deletingLastPathComponent() // Tests
            .deletingLastPathComponent() // macos
            .deletingLastPathComponent() // apps
            .deletingLastPathComponent() // repository root
        return try String(contentsOf: repositoryRoot.appendingPathComponent(relativePath), encoding: .utf8)
    }

    func testAppNeverPromotesItselfIntoTheDock() throws {
        for path in [
            "apps/macos/Sources/ARES/ARESApp.swift",
            "apps/macos/Sources/ARES/OnboardingWindow.swift",
            "apps/macos/Sources/ARES/ARESProductShell.swift",
            "apps/macos/Sources/ARES/ARESSettingsView.swift",
        ] {
            let source = try repositoryFile(path)
            XCTAssertFalse(
                source.contains("setActivationPolicy(.regular)"),
                "\(path) promotes ARES back into the Dock"
            )
        }
    }

    func testLaunchIsAccessoryOnly() throws {
        let source = try repositoryFile("apps/macos/Sources/ARES/ARESApp.swift")
        XCTAssertTrue(source.contains("setActivationPolicy(.accessory)"))
        // Match a declaration, not the prose explaining why there isn't one.
        for declaration in ["WindowGroup(", "WindowGroup {"] {
            XCTAssertFalse(
                source.contains(declaration),
                "a WindowGroup opens a window on every launch, which a menu-bar-only app must not do"
            )
        }
    }

    func testProductShellLoadsDesktopSurface() throws {
        let source = try repositoryFile("apps/macos/Sources/ARES/ARESProductShell.swift")
        XCTAssertTrue(source.contains("/desktop"))
        XCTAssertTrue(source.contains("webuiPort)/desktop"))
        XCTAssertFalse(
            source.contains("webuiPort)/\")"),
            "the Mac product shell must not load the browser UI at /"
        )
    }

    func testBundleDeclaresLSUIElement() throws {
        let script = try repositoryFile("apps/macos/build-app.sh")
        XCTAssertTrue(script.contains("<key>LSUIElement</key>"))
    }

    func testStatusItemClickRoutingStaysIntact() throws {
        let source = try repositoryFile("apps/macos/Sources/ARES/ARESApp.swift")
        // Assigning `statusItem.menu` permanently is exactly the bug that left
        // the status panel unreachable: the menu swallows the button action.
        XCTAssertTrue(source.contains("sendAction(on: [.leftMouseUp, .rightMouseUp])"))
        XCTAssertTrue(source.contains("statusItem.menu = nil"))
    }
}
