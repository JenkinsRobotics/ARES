import Foundation
import XCTest
@testable import ARES

final class WebUIServerManagerTests: XCTestCase {
    func testExplicitWebUIDirectoryPrecedesDiscoveryCandidates() {
        let explicit = URL(fileURLWithPath: "/opt/ares/webui")
        let candidates = WebUIServerManager.webUICandidates(
            resourceURL: URL(fileURLWithPath: "/Applications/ARES.app/Contents/Resources"),
            executableURL: URL(fileURLWithPath: "/Applications/ARES.app/Contents/MacOS/ARES"),
            homeDirectory: URL(fileURLWithPath: "/Users/tester"),
            environment: ["ARES_WEBUI_DIR": explicit.path],
            currentDirectory: "/tmp"
        )
        XCTAssertEqual(candidates.first, explicit)
    }

    func testPythonDiscoveryPrefersCanonicalDotVenv() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ares-python-precedence-\(UUID().uuidString)")
        let dotVenv = root.appendingPathComponent(".venv/bin/python")
        let legacyVenv = root.appendingPathComponent("venv/bin/python")
        try FileManager.default.createDirectory(
            at: dotVenv.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: legacyVenv.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        FileManager.default.createFile(atPath: dotVenv.path, contents: Data())
        FileManager.default.createFile(atPath: legacyVenv.path, contents: Data())
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dotVenv.path)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: legacyVenv.path)
        defer { try? FileManager.default.removeItem(at: root) }

        XCTAssertEqual(WebUIServerManager.pythonExecutable(in: root), dotVenv)
    }

    func testNativeRuntimeEnvironmentProvesMacAppOwnership() {
        let environment = WebUIServerManager.applyingNativeRuntimeEnvironment(
            to: ["UNCHANGED": "yes", "ARES_RUNTIME_OWNER": "standalone"],
            host: "127.0.0.1",
            port: 8788,
            reloadDevMode: false,
            instanceID: "mac-instance",
            stateDirectory: URL(fileURLWithPath: "/tmp/ares-native")
        )

        XCTAssertEqual(environment["ARES_RUNTIME_OWNER"], "mac_app")
        XCTAssertEqual(environment["ARES_RUNTIME_INSTANCE_ID"], "mac-instance")
        XCTAssertEqual(environment["ARES_NATIVE_STATE_DIR"], "/tmp/ares-native")
        XCTAssertEqual(environment["ARES_WEBUI_HOST"], "127.0.0.1")
        XCTAssertEqual(environment["ARES_WEBUI_PORT"], "8788")
        XCTAssertEqual(environment["ARES_WEBUI_RELOAD"], "0")
        XCTAssertEqual(environment["UNCHANGED"], "yes")
    }

    func testDevelopmentLauncherSelectsSiblingJaegerAIAndActiveCompanion() throws {
        let workspace = FileManager.default.temporaryDirectory
            .appendingPathComponent("ares-jaeger-dependency-\(UUID().uuidString)")
        let controller = workspace.appendingPathComponent("ARES/services/controller")
        let jaeger = workspace.appendingPathComponent("JaegerAI")
        try FileManager.default.createDirectory(
            at: controller,
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: jaeger.appendingPathComponent("jaeger_ai"),
            withIntermediateDirectories: true
        )
        let launcher = jaeger.appendingPathComponent("jaeger")
        try Data("#!/bin/sh\n".utf8).write(to: launcher)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: launcher.path)
        defer { try? FileManager.default.removeItem(at: workspace) }

        let environment = WebUIServerManager.applyingJaegerDependencyEnvironment(
            to: ["ARES_JaegerAI_INSTANCE": "legacy"],
            controllerDirectory: controller,
            homeDirectory: workspace.appendingPathComponent("home")
        )

        XCTAssertEqual(environment["ARES_JAEGER_HOME"], jaeger.path)
        XCTAssertEqual(environment["JAEGER_HOME"], jaeger.path)
        XCTAssertEqual(environment["ARES_JAEGER_SOURCE_DIR"], jaeger.path)
        XCTAssertNil(environment["ARES_JAEGER_INSTANCE"])
        XCTAssertNil(environment["ARES_JaegerAI_INSTANCE"])
    }

    func testDependencyValidationRejectsLegacyJaegerAIShape() throws {
        let legacy = FileManager.default.temporaryDirectory
            .appendingPathComponent("legacy-jaeger-\(UUID().uuidString)")
        try FileManager.default.createDirectory(
            at: legacy.appendingPathComponent("jaeger_os"),
            withIntermediateDirectories: true
        )
        let launcher = legacy.appendingPathComponent("jaeger")
        try Data("#!/bin/sh\n".utf8).write(to: launcher)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: launcher.path)
        defer { try? FileManager.default.removeItem(at: legacy) }

        XCTAssertFalse(WebUIServerManager.isJaegerAIProductRoot(legacy))
    }

    func testExplicitInvalidDependencyFailsClosed() throws {
        let workspace = FileManager.default.temporaryDirectory
            .appendingPathComponent("ares-jaeger-explicit-\(UUID().uuidString)")
        let controller = workspace.appendingPathComponent("ARES/services/controller")
        let validSibling = workspace.appendingPathComponent("JaegerAI")
        let stale = workspace.appendingPathComponent("old-jaeger")
        try FileManager.default.createDirectory(at: controller, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(
            at: validSibling.appendingPathComponent("jaeger_ai"),
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(at: stale, withIntermediateDirectories: true)
        FileManager.default.createFile(
            atPath: validSibling.appendingPathComponent("jaeger").path,
            contents: Data("#!/bin/sh\n".utf8),
            attributes: [.posixPermissions: 0o755]
        )
        defer { try? FileManager.default.removeItem(at: workspace) }

        let environment = WebUIServerManager.applyingJaegerDependencyEnvironment(
            to: ["ARES_JAEGER_HOME": stale.path],
            controllerDirectory: controller,
            homeDirectory: workspace.appendingPathComponent("home")
        )

        XCTAssertNil(environment["ARES_JAEGER_HOME"])
        XCTAssertNil(environment["JAEGER_HOME"])
        XCTAssertNil(environment["ARES_JAEGER_SOURCE_DIR"])
    }

    private var temporaryDirectory: URL!

    override func setUpWithError() throws {
        temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ares-webui-manager-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(
            at: temporaryDirectory,
            withIntermediateDirectories: true
        )
    }

    override func tearDownWithError() throws {
        if let temporaryDirectory {
            try? FileManager.default.removeItem(at: temporaryDirectory)
        }
    }

    func testWebUIDiscoveryRequiresFastAPIEntrypoint() throws {
        let legacyEntrypoint = temporaryDirectory.appendingPathComponent("server.py")
        try Data().write(to: legacyEntrypoint)
        XCTAssertFalse(WebUIServerManager.containsWebUI(at: temporaryDirectory))

        let fastAPIEntrypoint = temporaryDirectory
            .appendingPathComponent(WebUIServerManager.webUIEntrypoint)
        try FileManager.default.createDirectory(
            at: fastAPIEntrypoint.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data().write(to: fastAPIEntrypoint)
        XCTAssertTrue(WebUIServerManager.containsWebUI(at: temporaryDirectory))
    }

    func testPythonDiscoverySupportsInstallerAndDotVenvLayouts() throws {
        XCTAssertNil(WebUIServerManager.pythonExecutable(in: temporaryDirectory))

        let dotVenvPython = try makeExecutable(".venv/bin/python")
        XCTAssertEqual(
            WebUIServerManager.pythonExecutable(in: temporaryDirectory),
            dotVenvPython
        )

        _ = try makeExecutable("venv/bin/python")
        XCTAssertEqual(
            WebUIServerManager.pythonExecutable(in: temporaryDirectory),
            dotVenvPython,
            "The dependency-complete canonical .venv must take precedence over a stale legacy venv"
        )
    }

    func testExplicitAresHomePrecedesDefaultInstall() {
        let candidates = WebUIServerManager.webUICandidates(
            resourceURL: nil,
            executableURL: nil,
            homeDirectory: URL(fileURLWithPath: "/Users/example"),
            environment: ["ARES_HOME": "/tmp/isolated-ares"],
            currentDirectory: "/workspace"
        )
        XCTAssertEqual(candidates[0].path, "/workspace/services/controller")
        XCTAssertEqual(candidates[1].path, "/workspace/webui") // legacy
        XCTAssertEqual(candidates[2].path, "/tmp/isolated-ares/services/controller")
        XCTAssertEqual(candidates[3].path, "/tmp/isolated-ares/webui") // legacy
        XCTAssertEqual(candidates[4].path, "/Users/example/.ares/services/controller")
        XCTAssertEqual(candidates[5].path, "/Users/example/.ares/webui") // legacy
    }

    func testDevelopmentAppBundleDiscoversRepositoryController() {
        let candidates = WebUIServerManager.webUICandidates(
            resourceURL: URL(fileURLWithPath: "/Users/tester/GitHub/ARES/apps/macos/ARES.app/Contents/Resources"),
            executableURL: URL(fileURLWithPath: "/Users/tester/GitHub/ARES/apps/macos/ARES.app/Contents/MacOS/ARES"),
            homeDirectory: URL(fileURLWithPath: "/Users/tester"),
            environment: [:],
            currentDirectory: "/"
        )

        XCTAssertTrue(
            candidates.contains(URL(fileURLWithPath: "/Users/tester/GitHub/ARES/services/controller"))
        )
    }

    func testInstalledAppBundleDiscoversRepositoryControllerViaCtlEnvAndCommonPaths() throws {
        let root = temporaryDirectory.appendingPathComponent("installed-app-test")
        let aresHome = root.appendingPathComponent(".ares")
        let repoRoot = root.appendingPathComponent("GitHub/ARES/services/controller")
        try FileManager.default.createDirectory(at: aresHome, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: repoRoot, withIntermediateDirectories: true)

        let ctlEnv = aresHome.appendingPathComponent("webui.ctl.env")
        try "REPO_ROOT=\(repoRoot.path)\n".write(to: ctlEnv, atomically: true, encoding: .utf8)

        let candidates = WebUIServerManager.webUICandidates(
            resourceURL: URL(fileURLWithPath: "/Users/tester/Applications/ARES.app/Contents/Resources"),
            executableURL: URL(fileURLWithPath: "/Users/tester/Applications/ARES.app/Contents/MacOS/ARES"),
            homeDirectory: root,
            environment: [:],
            currentDirectory: "/"
        )

        XCTAssertTrue(
            candidates.contains(where: { $0.standardizedFileURL.path == repoRoot.standardizedFileURL.path })
        )
    }

    func testAresHealthResponseRequiresHealthyAresPayload() throws {
        let currentPayload = try JSONSerialization.data(withJSONObject: [
            "service": "ares-webui",
            "status": "ok",
        ])
        XCTAssertTrue(WebUIServerManager.isAresHealthResponse(statusCode: 200, data: currentPayload))

        let upgradePayload = try JSONSerialization.data(withJSONObject: [
            "status": "ok",
            "accept_loop": ["server": "uvicorn"],
        ])
        XCTAssertTrue(WebUIServerManager.isAresHealthResponse(statusCode: 200, data: upgradePayload))

        let unrelatedPayload = try JSONSerialization.data(withJSONObject: ["status": "ok"])
        XCTAssertFalse(WebUIServerManager.isAresHealthResponse(statusCode: 200, data: unrelatedPayload))
        XCTAssertFalse(WebUIServerManager.isAresHealthResponse(statusCode: 503, data: currentPayload))
    }

    /// A standalone controller (started outside this app, e.g. `ares start`)
    /// must be distinguishable from both a foreign process and another
    /// mac_app-owned instance — that distinction is what makes it safe to
    /// offer the user a "take over" action on port conflict.
    func testRuntimeOwnerDistinguishesStandaloneFromMacAppAndForeignProcesses() throws {
        let standalonePayload = try JSONSerialization.data(withJSONObject: [
            "service": "ares-webui",
            "status": "ok",
            "runtime_owner": "standalone",
        ])
        XCTAssertEqual(
            WebUIServerManager.runtimeOwner(statusCode: 200, data: standalonePayload),
            "standalone"
        )

        let macAppPayload = try JSONSerialization.data(withJSONObject: [
            "service": "ares-webui",
            "status": "ok",
            "runtime_owner": "mac_app",
        ])
        XCTAssertEqual(
            WebUIServerManager.runtimeOwner(statusCode: 200, data: macAppPayload),
            "mac_app"
        )

        // Not an ARES health response at all — a genuinely foreign process
        // must never be reported as any kind of owner.
        let foreignPayload = try JSONSerialization.data(withJSONObject: ["status": "ok"])
        XCTAssertNil(WebUIServerManager.runtimeOwner(statusCode: 200, data: foreignPayload))
    }

    private func makeExecutable(_ relativePath: String) throws -> URL {
        let url = temporaryDirectory.appendingPathComponent(relativePath)
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data("#!/bin/sh\n".utf8).write(to: url)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: url.path
        )
        return url
    }
}
