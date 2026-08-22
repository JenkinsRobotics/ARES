import Foundation
import Combine
import Network
import Darwin
import ARESCore

private final class PortProbeCompletion: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false

    func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !completed else { return false }
        completed = true
        return true
    }
}

@MainActor
public final class WebUIServerManager: ObservableObject {
    public static let shared = WebUIServerManager()

    nonisolated static let webUIEntrypoint = "fastapi_app/main.py"

    @Published public var isRunning = false
    @Published public var portConflict = false
    // Set only when the process occupying the port answers the ARES health
    // check AND self-reports as a "standalone" instance (started outside
    // this app, e.g. via `ares start`/ctl.sh) — never for a genuinely
    // foreign process, and never for another mac_app-owned instance. This
    // is the one case where offering the user a "stop it and take over"
    // action is safe: it's provably ARES's own controller, just not one
    // this app instance launched. `start()` used to just give up silently
    // here with no way to start/stop/restart anything (the user's own
    // controller effectively became invisible to the app).
    @Published public var conflictingStandaloneInstance = false
    /// True when the controller answering on the port was started by
    /// something else (`ares start`, ctl.sh, launchd, or a previous instance
    /// of this app) and this app adopted it instead of refusing to run.
    /// Stop/Restart still work in this state — they drive ctl.sh rather than
    /// an owned `Process` handle.
    @Published public var adoptedExternalController = false
    @Published public var serverHealth = "Stopped" // "Stopped", "Starting...", "Running (Healthy)", "Running (Degraded)", "Running (Unreachable)", "Failed"
    @Published public var recentLogs = ""

    private var process: Process?
    /// Root PID this app is responsible for reaping on Quit — the owned
    /// uvicorn child, or an adopted listener on the WebUI port.
    private var supervisedPid: pid_t?
    private var watchdog: Process?
    private var healthCheckTimer: Timer?
    private var logTimer: Timer?

    private init() {
        // Periodically check logs and health if running
        healthCheckTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                await self?.checkHealth()
            }
        }
        
        logTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.readLastLogs()
            }
        }
    }

    public func start() async {
        guard process == nil else { return }
        
        let config = ARESConfiguration.shared
        let host = config.webuiHost
        let port = config.webuiPort
        
        serverHealth = "Checking port..."

        // Ownership is decided by what is provably running, not by which
        // process happened to spawn it.
        //
        // This used to reason from private in-memory state ("did *this* app
        // instance launch it?"), which is lost on every app restart, rebuild,
        // or crash. The app would then meet its own still-healthy controller,
        // fail to recognize it, and report "Port 8788 is owned by another
        // process" — offering no way to start, stop, or restart a server that
        // was working the whole time. There are three legitimate ways to
        // start the controller (this app, `ares start`, ctl.sh/launchd), so
        // "I didn't personally spawn it" was never a sound basis for calling
        // something foreign.
        //
        // A live /health answer identifying itself as ares-webui IS the proof
        // of ownership, and it survives app restarts because it lives in the
        // running system rather than in this object. So:
        //   • answers as ARES  → adopt it: report Running (External); Stop and
        //     Restart drive it through ctl.sh, the same lifecycle every other
        //     start path already uses.
        //   • answers as something else, or not at all → a genuinely foreign
        //     process. That is the only real conflict, and it keeps the error.
        // Killing and respawning a healthy ARES controller to satisfy a
        // bookkeeping preference would drop the user's in-flight turns for no
        // benefit, so adoption is the default rather than a recovery action.
        let probeHost = Self.loopbackIfNetworkBind(host)
        let inUse = await isPortInUse(port, host: probeHost)
        if inUse {
            if let owner = await Self.runtimeOwner(host: probeHost, port: port) {
                portConflict = false
                conflictingStandaloneInstance = false
                adoptedExternalController = true
                isRunning = true
                serverHealth = "Running (External)"
                attachSupervisor(to: ProcessTree.listeningPids(port: port).first)
                print("[ARES] Adopted existing ARES controller on \(probeHost):\(port) (runtime_owner=\(owner))")
                return
            }
            portConflict = true
            conflictingStandaloneInstance = false
            adoptedExternalController = false
            serverHealth = "Port \(port) is owned by another process"
            return
        }
        portConflict = false
        conflictingStandaloneInstance = false
        adoptedExternalController = false
        serverHealth = "Starting..."

        let webuiDir = findWebUIDir()
        guard let dir = webuiDir else {
            serverHealth = "WebUI directory not found"
            return
        }

        let process = Process()
        process.currentDirectoryURL = dir
        // Prefer the repository's canonical .venv. A stale legacy venv may
        // contain Python but not the WebUI dependencies (notably Uvicorn).
        let fm = FileManager.default
        guard let python = Self.pythonExecutable(in: dir, fileManager: fm) else {
            serverHealth = "Python environment not found — run install.sh"
            return
        }
        process.executableURL = python
        process.arguments = ["-m", "uvicorn", "fastapi_app.main:app", "--port", String(port), "--host", host]
        
        var env = ProcessInfo.processInfo.environment
        env = Self.applyingNativeRuntimeEnvironment(
            to: env,
            host: host,
            port: port,
            reloadDevMode: config.reloadDevMode,
            allowUnauthenticatedNetwork: config.allowUnauthenticatedNetwork,
            instanceID: NativeSystemBridge.shared.instanceID,
            stateDirectory: config.configDirectory
        )
        env = Self.applyingJaegerDependencyEnvironment(
            to: env,
            controllerDirectory: dir,
            homeDirectory: FileManager.default.homeDirectoryForCurrentUser
        )
        env["ARES_ROLE"] = config.aresRole
        env["ARES_DEVICE_ID"] = config.aresDeviceID
        env["ARES_AI_ID"] = config.aresAIID
        env["ARES_PRIMARY_URL"] = config.aresPrimaryURL
        env["ARES_CONTINUITY_DIR"] = config.aresContinuityDir
        if let nativeMCPCommand = Self.nativeMCPExecutable() {
            env["ARES_NATIVE_MCP_COMMAND"] = nativeMCPCommand.path
        }
        process.environment = env

        // Redirect logs to webui.log (truncate if > 10MB to avoid disk bloat)
        let logFileURL = config.configDirectory.appendingPathComponent("webui.log")
        if FileManager.default.fileExists(atPath: logFileURL.path) {
            if let attrs = try? FileManager.default.attributesOfItem(atPath: logFileURL.path),
               let size = attrs[.size] as? UInt64, size > 10 * 1024 * 1024 {
                try? "".write(to: logFileURL, atomically: true, encoding: .utf8)
            }
        } else {
            FileManager.default.createFile(atPath: logFileURL.path, contents: nil)
        }
        if let logFileHandle = try? FileHandle(forWritingTo: logFileURL) {
            logFileHandle.seekToEndOfFile()
            process.standardOutput = logFileHandle
            process.standardError = logFileHandle
        }

        do {
            try process.run()
            self.process = process
            self.isRunning = true
            self.serverHealth = "Starting..."
            attachSupervisor(to: process.processIdentifier)
            print("[ARES] WebUI server started on http://\(host):\(port)")
        } catch {
            self.serverHealth = "Failed: \(error.localizedDescription)"
            print("[ARES] Failed to start WebUI: \(error)")
        }
    }

    nonisolated static func applyingNativeRuntimeEnvironment(
        to base: [String: String],
        host: String,
        port: Int,
        reloadDevMode: Bool,
        allowUnauthenticatedNetwork: Bool = true,
        instanceID: String,
        stateDirectory: URL
    ) -> [String: String] {
        var environment = base
        environment["ARES_WEBUI_HOST"] = host
        environment["ARES_WEBUI_PORT"] = String(port)
        environment["ARES_WEBUI_RELOAD"] = reloadDevMode ? "1" : "0"
        environment["ARES_WEBUI_ALLOW_UNAUTHENTICATED_NETWORK"] = allowUnauthenticatedNetwork ? "1" : "0"
        environment["ARES_RUNTIME_OWNER"] = "mac_app"
        environment["ARES_RUNTIME_INSTANCE_ID"] = instanceID
        environment["ARES_NATIVE_STATE_DIR"] = stateDirectory.path
        return environment
    }

    nonisolated static func applyingJaegerDependencyEnvironment(
        to base: [String: String],
        controllerDirectory: URL,
        homeDirectory: URL,
        fileManager: FileManager = .default
    ) -> [String: String] {
        var environment = base
        // Retired JaegerAI variables are migration inputs inside the controller,
        // never values emitted by the current Mac launcher.
        for key in [
            "ARES_JaegerAI_DIR", "ARES_JaegerAI_CONFIG_PATH", "ARES_JaegerAI_INSTANCE",
            "JaegerAI_HOME", "JaegerAI_INSTANCE_NAME",
        ] {
            environment.removeValue(forKey: key)
        }

        let aresRoot = controllerDirectory
            .deletingLastPathComponent() // services
            .deletingLastPathComponent() // ARES repository
        let siblingCheckout = aresRoot
            .deletingLastPathComponent()
            .appendingPathComponent("JaegerAI", isDirectory: true)
        let standardInstall = homeDirectory.appendingPathComponent("jaeger", isDirectory: true)

        let explicitSelection = ["ARES_JAEGER_HOME", "JAEGER_HOME", "ARES_JAEGER_SOURCE_DIR"]
            .compactMap { key -> (key: String, url: URL)? in
                guard let raw = environment[key]?.trimmingCharacters(in: .whitespacesAndNewlines),
                      !raw.isEmpty
                else { return nil }
                return (key, URL(fileURLWithPath: raw, isDirectory: true))
            }
            .first
        let selected: URL?
        let selectedIsSource: Bool
        if let explicitSelection {
            // Explicit dependency selection fails closed. A stale JaegerAI path
            // must never be hidden by switching to another checkout.
            selected = isJaegerAIProductRoot(explicitSelection.url, fileManager: fileManager)
                ? explicitSelection.url
                : nil
            selectedIsSource = explicitSelection.key == "ARES_JAEGER_SOURCE_DIR"
        } else {
            // Repository builds prefer the adjacent development checkout.
            // Packaged installs fall through to the conventional top-level path.
            selected = [siblingCheckout, standardInstall].first(where: {
                isJaegerAIProductRoot($0, fileManager: fileManager)
            })
            selectedIsSource = selected?.standardizedFileURL == siblingCheckout.standardizedFileURL
        }

        guard let selected else {
            environment.removeValue(forKey: "ARES_JAEGER_HOME")
            environment.removeValue(forKey: "JAEGER_HOME")
            environment.removeValue(forKey: "ARES_JAEGER_SOURCE_DIR")
            environment.removeValue(forKey: "ARES_JAEGER_INSTANCE")
            return environment
        }

        environment["ARES_JAEGER_HOME"] = selected.path
        environment["JAEGER_HOME"] = selected.path
        if selectedIsSource {
            environment["ARES_JAEGER_SOURCE_DIR"] = selected.path
        } else {
            environment.removeValue(forKey: "ARES_JAEGER_SOURCE_DIR")
        }

        // The controller's shared path resolver selects the active instance.
        // The app intentionally does not traverse Jaeger's runtime layout.
        environment.removeValue(forKey: "ARES_JAEGER_INSTANCE")
        return environment
    }

    nonisolated static func isJaegerAIProductRoot(
        _ root: URL,
        fileManager: FileManager = .default
    ) -> Bool {
        var isDirectory: ObjCBool = false
        let package = root.appendingPathComponent("jaeger_ai", isDirectory: true)
        guard fileManager.fileExists(atPath: package.path, isDirectory: &isDirectory),
              isDirectory.boolValue
        else { return false }
        let launcher = root.appendingPathComponent("jaeger")
        return fileManager.isExecutableFile(atPath: launcher.path)
    }

    /// Stop the controller and every descendant (Jaeger bridge, native MCP)
    /// before returning. SIGTERM on the uvicorn handle alone leaves
    /// grandchildren reparented to launchd; the tree snapshot is taken
    /// while those processes still parent to uvicorn.
    public func stop() async {
        serverHealth = "Stopping..."
        let config = ARESConfiguration.shared
        let port = config.webuiPort
        var pids = Set<pid_t>()
        let ownedPid = process?.processIdentifier
        if let ownedPid { pids.insert(ownedPid) }
        if let supervised = supervisedPid { pids.insert(supervised) }
        pids.formUnion(process.map { ProcessTree.descendants(of: $0.processIdentifier) } ?? [])
        if let supervised = supervisedPid {
            pids.formUnion(ProcessTree.descendants(of: supervised))
        }
        let listeningAsAres: Bool
        if adoptedExternalController {
            listeningAsAres = true
        } else {
            listeningAsAres = await isAresControllerListening()
        }
        if listeningAsAres {
            pids.formUnion(ProcessTree.listeningPids(port: port))
        }
        let rescanRoot = ownedPid ?? supervisedPid ?? pids.first

        process = nil
        detachSupervisor()

        if !pids.isEmpty {
            await ProcessTree.terminate(pids: pids, graceSeconds: 4, rescanRoot: rescanRoot)
        }

        if await isAresControllerListening() {
            await stopExternalController()
        }

        let leftovers = pids.filter { ProcessTree.isAlive($0) }
        isRunning = false
        adoptedExternalController = false
        serverHealth = leftovers.isEmpty ? "Stopped" : "Stop timed out"
    }

    public func restart() async {
        await stop()
        await start()
    }

    /// Gracefully stop a standalone controller this app didn't launch, so
    /// the port frees up and a subsequent ``start()`` can take over.
    ///
    /// Only ever call this when ``conflictingStandaloneInstance`` is true —
    /// that flag is only set when the occupying process proved itself to be
    /// ARES's own controller via a live health check, matching the same
    /// safety bar the shell CLI (`bin/ares`) already applies before it
    /// hands lifecycle ownership to this app. This does not run on its own;
    /// it exists so the UI can offer the user an explicit "take over"
    /// action instead of leaving them with no start/stop/restart control at
    /// all over a controller that is, in fact, theirs.
    public func stopConflictingStandaloneInstance() async {
        guard conflictingStandaloneInstance || adoptedExternalController else { return }
        await stopExternalController()
    }

    /// True when the configured WebUI port answers an ARES health check.
    private func isAresControllerListening() async -> Bool {
        let config = ARESConfiguration.shared
        let host = Self.loopbackIfNetworkBind(config.webuiHost)
        guard let url = URL(string: "http://\(host):\(config.webuiPort)/health") else {
            return false
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.0
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse
        else { return false }
        return Self.isAresHealthResponse(statusCode: http.statusCode, data: data)
    }

    /// Stop a controller this app did not spawn, via ctl.sh.
    ///
    /// Reached both by Stop on an adopted controller and by the older
    /// conflict-recovery path. ctl.sh owns the PID file and the graceful
    /// shutdown sequence, so routing through it keeps every start/stop route
    /// agreeing about what is running instead of each tracking its own idea
    /// of ownership.
    private func stopExternalController() async {
        guard let dir = findWebUIDir() else {
            serverHealth = "WebUI directory not found"
            return
        }
        let ctlScript = dir.appendingPathComponent("ctl.sh")
        guard FileManager.default.isExecutableFile(atPath: ctlScript.path)
            || FileManager.default.fileExists(atPath: ctlScript.path)
        else {
            serverHealth = "ctl.sh not found — stop the other instance manually"
            return
        }
        serverHealth = "Stopping other instance..."
        let config = ARESConfiguration.shared
        var env = ProcessInfo.processInfo.environment
        env["ARES_WEBUI_HOST"] = config.webuiHost
        env["ARES_WEBUI_PORT"] = String(config.webuiPort)

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/bash")
        proc.arguments = [ctlScript.path, "stop"]
        proc.environment = env
        proc.currentDirectoryURL = dir

        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            proc.terminationHandler = { _ in continuation.resume() }
            do {
                try proc.run()
            } catch {
                serverHealth = "Failed to stop other instance: \(error.localizedDescription)"
                continuation.resume()
            }
        }

        // Give the port a moment to actually release before the caller
        // retries start() — ctl.sh's own stop_cmd already polls/escalates
        // internally, but the OS can lag a beat behind the process exiting.
        let probeHost = Self.loopbackIfNetworkBind(config.webuiHost)
        let deadline = Date().addingTimeInterval(3.0)
        while await isPortInUse(config.webuiPort, host: probeHost), Date() < deadline {
            try? await Task.sleep(nanoseconds: 200_000_000)
        }

        var stillInUse = await isPortInUse(config.webuiPort, host: probeHost)
        if stillInUse {
            // If ctl.sh stop didn't release the port (e.g. process started by a prior app instance),
            // terminate the occupying process directly.
            let killProc = Process()
            killProc.executableURL = URL(fileURLWithPath: "/bin/bash")
            killProc.arguments = ["-c", "pids=$(lsof -ti :\(config.webuiPort)); if [ -n \"$pids\" ]; then kill -15 $pids 2>/dev/null; sleep 0.5; kill -9 $pids 2>/dev/null; fi"]
            try? killProc.run()
            killProc.waitUntilExit()

            let killDeadline = Date().addingTimeInterval(3.0)
            while await isPortInUse(config.webuiPort, host: probeHost), Date() < killDeadline {
                try? await Task.sleep(nanoseconds: 200_000_000)
            }
            stillInUse = await isPortInUse(config.webuiPort, host: probeHost)
        }

        if stillInUse {
            portConflict = true
            conflictingStandaloneInstance = true
            serverHealth = "Failed to stop other instance on port \(config.webuiPort)"
            return
        }

        portConflict = false
        conflictingStandaloneInstance = false
        adoptedExternalController = false
        isRunning = false
        serverHealth = "Stopped"
    }

    private func checkHealth() async {
        var exitedProcess: Process?
        if let p = process, !p.isRunning {
            exitedProcess = p
            process = nil
        }

        guard isRunning || exitedProcess != nil else {
            return
        }

        if let exitedProcess {
            recordHealthFailure(exitedProcess: exitedProcess, fallback: "Exited")
            return
        }

        let config = ARESConfiguration.shared
        let probeHost = Self.loopbackIfNetworkBind(config.webuiHost)
        let urlString = "http://\(probeHost):\(config.webuiPort)/health"
        guard let url = URL(string: urlString) else { return }
        
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.0
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let httpResp = response as? HTTPURLResponse,
               Self.isAresHealthResponse(statusCode: httpResp.statusCode, data: data) {
                isRunning = true
                // Keep an adopted controller labelled as external so the UI
                // (and the user) can tell "healthy, and this app supervises
                // it" from "healthy, started elsewhere" — both are fine, and
                // neither is an error.
                serverHealth = adoptedExternalController ? "Running (External)" : "Running (Healthy)"
            } else {
                recordHealthFailure(exitedProcess: exitedProcess, fallback: "Running (Degraded)")
            }
        } catch {
            recordHealthFailure(exitedProcess: exitedProcess, fallback: "Running (Unreachable)")
        }
    }

    /// Adopt an already-running ARES controller at app launch.
    ///
    /// The health poller only re-labels a server it already believes is
    /// running; on a cold start (`isRunning == false`, no owned process) it
    /// returns immediately, so an app relaunched next to a live controller
    /// would sit at "Stopped" until someone pressed Start. Probing once at
    /// startup means the menu bar reflects reality from the first tick.
    public func adoptRunningControllerIfPresent() async {
        guard process == nil, !isRunning else { return }
        let config = ARESConfiguration.shared
        let probeHost = Self.loopbackIfNetworkBind(config.webuiHost)
        guard await Self.runtimeOwner(host: probeHost, port: config.webuiPort) != nil else { return }
        portConflict = false
        conflictingStandaloneInstance = false
        adoptedExternalController = true
        isRunning = true
        serverHealth = "Running (External)"
        attachSupervisor(to: ProcessTree.listeningPids(port: config.webuiPort).first)
    }

    private func attachSupervisor(to pid: pid_t?) {
        detachSupervisor()
        guard let pid, pid > 1 else { return }
        supervisedPid = pid
        watchdog = ProcessTree.startParentDeathWatchdog(parent: getpid(), root: pid)
    }

    private func detachSupervisor() {
        watchdog?.terminate()
        watchdog = nil
        supervisedPid = nil
    }

    private func recordHealthFailure(exitedProcess: Process?, fallback: String) {
        if let exitedProcess {
            isRunning = false
            serverHealth = "Exited (code: \(exitedProcess.terminationStatus))"
        } else {
            serverHealth = fallback
        }
    }

    nonisolated static func isAresHealthResponse(statusCode: Int, data: Data) -> Bool {
        guard statusCode == 200,
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return false
        }

        // New servers expose an explicit service identity. Keep compatibility
        // with existing ARES launch agents during an in-place app upgrade.
        if payload["service"] as? String == "ares-webui" {
            return true
        }
        if let acceptLoop = payload["accept_loop"] as? [String: Any],
           acceptLoop["server"] as? String == "uvicorn",
           payload["status"] as? String == "ok" {
            return true
        }
        return false
    }

    nonisolated static func loopbackIfNetworkBind(_ host: String) -> String {
        (host == "0.0.0.0" || host == "::") ? "127.0.0.1" : host
    }

    /// The occupying process's self-reported ``runtime_owner`` ("standalone"
    /// or "mac_app"), or ``nil`` when it isn't answering an ARES health
    /// check at all (a genuinely foreign process). Mirrors the shell CLI's
    /// own ``_ares_runtime_owner()`` check in ``bin/ares`` — the app and the
    /// CLI should agree on what's safe to take over.
    nonisolated static func runtimeOwner(host: String, port: Int) async -> String? {
        guard let url = URL(string: "http://\(host):\(port)/health") else { return nil }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.0
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let httpResp = response as? HTTPURLResponse
        else { return nil }
        return runtimeOwner(statusCode: httpResp.statusCode, data: data)
    }

    /// Pure parsing half of ``runtimeOwner(host:port:)``, split out so it's
    /// testable without a live server (mirrors ``isAresHealthResponse``).
    nonisolated static func runtimeOwner(statusCode: Int, data: Data) -> String? {
        guard isAresHealthResponse(statusCode: statusCode, data: data),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return payload["runtime_owner"] as? String
    }

    private func readLastLogs() {
        let config = ARESConfiguration.shared
        let logFileURL = config.configDirectory.appendingPathComponent("webui.log")
        guard FileManager.default.fileExists(atPath: logFileURL.path) else { return }
        
        do {
            let content = try String(contentsOf: logFileURL, encoding: .utf8)
            let lines = content.components(separatedBy: .newlines)
            let lastLines = lines.suffix(100)
            self.recentLogs = lastLines.joined(separator: "\n")
        } catch {}
    }

    private func isPortInUse(_ port: Int, host: String) async -> Bool {
        return await withCheckedContinuation { continuation in
            let endpoint = NWEndpoint.hostPort(host: NWEndpoint.Host(host), port: NWEndpoint.Port(integerLiteral: UInt16(port)))
            let connection = NWConnection(to: endpoint, using: .tcp)
            let completion = PortProbeCompletion()
            let finish: @Sendable (Bool) -> Void = { result in
                guard completion.claim() else { return }
                connection.cancel()
                continuation.resume(returning: result)
            }
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    finish(true)
                case .waiting(_):
                    finish(false)
                case .failed(_):
                    finish(false)
                case .cancelled:
                    finish(false)
                default:
                    break
                }
            }
            connection.start(queue: .global())
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.3) {
                finish(false)
            }
        }
    }

    private func findWebUIDir() -> URL? {
        for candidate in Self.webUICandidates() where Self.containsWebUI(at: candidate) {
            return candidate
        }
        return nil
    }

    nonisolated static func webUICandidates(
        resourceURL: URL? = Bundle.main.resourceURL,
        executableURL: URL? = Bundle.main.executableURL,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        currentDirectory: String = FileManager.default.currentDirectoryPath
    ) -> [URL] {
        var candidates: [URL] = []
        if let explicitWebUI = environment["ARES_WEBUI_DIR"], !explicitWebUI.isEmpty {
            candidates.append(URL(fileURLWithPath: explicitWebUI))
        }
        if let resourceURL {
            candidates.append(resourceURL.appendingPathComponent("services/controller"))
            candidates.append(resourceURL.appendingPathComponent("webui")) // legacy path
        }
        var directory = executableURL?.deletingLastPathComponent()
        // A development bundle lives at apps/macos/ARES.app; reaching the
        // repository root from Contents/MacOS requires walking beyond the app
        // wrapper and both source-layout directories.
        for _ in 0..<8 {
            guard let current = directory else { break }
            candidates.append(current.appendingPathComponent("services/controller"))
            candidates.append(current.appendingPathComponent("webui")) // legacy path
            directory = current.deletingLastPathComponent()
        }
        candidates.append(URL(fileURLWithPath: currentDirectory).appendingPathComponent("services/controller"))
        candidates.append(URL(fileURLWithPath: currentDirectory).appendingPathComponent("webui")) // legacy path
        if let aresHome = environment["ARES_HOME"], !aresHome.isEmpty {
            candidates.append(URL(fileURLWithPath: aresHome).appendingPathComponent("services/controller"))
            candidates.append(URL(fileURLWithPath: aresHome).appendingPathComponent("webui")) // legacy path
        }
        candidates.append(homeDirectory.appendingPathComponent(".ares/services/controller"))
        candidates.append(homeDirectory.appendingPathComponent(".ares/webui")) // legacy path

        // Read REPO_ROOT from webui.ctl.env if written by ctl.sh or a previous controller run
        let aresHomeURL = environment["ARES_HOME"].flatMap { !$0.isEmpty ? URL(fileURLWithPath: $0) : nil }
            ?? homeDirectory.appendingPathComponent(".ares", isDirectory: true)
        let ctlEnvFile = aresHomeURL.appendingPathComponent("webui.ctl.env")
        if let content = try? String(contentsOf: ctlEnvFile, encoding: .utf8) {
            for line in content.components(separatedBy: .newlines) {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if trimmed.hasPrefix("REPO_ROOT=") {
                    let path = trimmed.dropFirst("REPO_ROOT=".count)
                        .trimmingCharacters(in: CharacterSet(charactersIn: "\"'\n\r\t "))
                    if !path.isEmpty {
                        candidates.append(URL(fileURLWithPath: path))
                    }
                }
            }
        }

        // Check common developer repository checkout locations in home directory
        let commonRepoSubpaths = [
            "GitHub/ARES/services/controller",
            "Developer/ARES/services/controller",
            "Projects/ARES/services/controller",
            "src/ARES/services/controller",
            "ARES/services/controller",
            "ares/services/controller",
        ]
        for subpath in commonRepoSubpaths {
            candidates.append(homeDirectory.appendingPathComponent(subpath))
        }

        return candidates
    }

    nonisolated static func containsWebUI(
        at directory: URL,
        fileManager: FileManager = .default
    ) -> Bool {
        fileManager.fileExists(
            atPath: directory.appendingPathComponent(webUIEntrypoint).path
        )
    }

    nonisolated static func pythonExecutable(
        in directory: URL,
        fileManager: FileManager = .default
    ) -> URL? {
        for relativePath in [".venv/bin/python", "venv/bin/python"] {
            let candidate = directory.appendingPathComponent(relativePath)
            if fileManager.isExecutableFile(atPath: candidate.path) {
                return candidate
            }
        }
        return nil
    }

    nonisolated static func nativeMCPExecutable(
        executableURL: URL? = Bundle.main.executableURL,
        fileManager: FileManager = .default
    ) -> URL? {
        guard let executableURL else { return nil }
        let candidate = executableURL
            .deletingLastPathComponent()
            .appendingPathComponent("ARESNativeMCP")
        return fileManager.isExecutableFile(atPath: candidate.path) ? candidate : nil
    }

}
