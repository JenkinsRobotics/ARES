import SwiftUI
import AppKit
import WebKit
import ARESCore

/// Owns the single ARES window.
///
/// ARES is a menu-bar-only app, so there is no SwiftUI `WindowGroup` to
/// recreate a window once the user closes it. AppKit owns the window directly
/// and the status menu is the only thing that opens one.
@MainActor
final class ARESWindowCoordinator: NSObject, NSWindowDelegate {
    static let shared = ARESWindowCoordinator()

    private var window: NSWindow?

    /// Invoked after the ARES window closes so the app delegate can apply the
    /// user's background-operation preference.
    var onWindowClosed: (() -> Void)?

    var hasVisibleWindow: Bool { window?.isVisible ?? false }

    func openMainWindow() {
        if let window {
            window.deminiaturize(nil)
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let created = NSWindow(contentViewController: NSHostingController(rootView: ARESMainScene()))
        created.title = "ARES"
        created.styleMask = [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView]
        created.titlebarAppearsTransparent = true
        created.titleVisibility = .hidden
        created.tabbingMode = .disallowed
        // The coordinator holds the only reference. Without this AppKit frees
        // the window on close and reopening from the menu crashes.
        created.isReleasedWhenClosed = false
        created.setContentSize(NSSize(width: 1200, height: 800))
        created.contentMinSize = NSSize(width: 1024, height: 700)
        created.delegate = self
        created.center()
        window = created

        created.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func closeMainWindow() {
        window?.close()
    }

    func windowWillClose(_ notification: Notification) {
        guard (notification.object as? NSWindow) === window else { return }
        onWindowClosed?()
    }
}

private struct ARESMainScene: View {
    var body: some View {
        ARESMainView()
            .frame(minWidth: 1024, minHeight: 700)
            .preferredColorScheme(.dark)
    }
}

@MainActor
@main
struct ARESApp: App {
    @NSApplicationDelegateAdaptor(ARESAppDelegate.self) var appDelegate

    /// Settings is the only declared scene. A `WindowGroup` would open a window
    /// on every launch, which a menu-bar-only app must never do; the ARES
    /// window is created on demand by `ARESWindowCoordinator`.
    var body: some Scene {
        Settings {
            ARESSettingsView()
        }
    }
}

// MARK: - Main View

/// Primary on-device product entry. Full capacity lives in `ARESProductShell`
/// (native destinations + routed shared surfaces). The WebUI alone is the
/// remote/light client for other devices over LAN or a trusted tailnet.
struct ARESMainView: View {
    @ObservedObject private var serverManager = WebUIServerManager.shared
    @ObservedObject private var onboardingManager = OnboardingManager.shared

    var body: some View {
        if onboardingManager.needsOnboarding {
            OnboardingView()
                .frame(minWidth: 800, minHeight: 600)
        } else if serverManager.isRunning {
            ARESProductShell()
        } else {
            ARESBootSplashView(status: serverManager.serverHealth)
        }
    }
}

/// Shown only while the local controller is starting.
struct ARESBootSplashView: View {
    let status: String

    var body: some View {
        ZStack {
            Color(red: 0.063, green: 0.063, blue: 0.078)
                .ignoresSafeArea()
            VStack(spacing: 0) {
                Spacer()
                Text("✦")
                    .font(.system(size: 52))
                    .foregroundColor(Color(red: 0.85, green: 0.70, blue: 0.35))
                    .padding(.bottom, 12)
                Text("ARES")
                    .font(.system(size: 32, weight: .light, design: .default))
                    .foregroundColor(.white)
                    .tracking(6)
                Text("App for your Companion · workers execute")
                    .font(.system(size: 12))
                    .foregroundColor(Color.white.opacity(0.45))
                    .padding(.top, 10)
                Spacer()
                ProgressView()
                    .scaleEffect(0.8)
                    .colorMultiply(.white)
                    .padding(.bottom, 8)
                Text(status)
                    .foregroundColor(Color.white.opacity(0.4))
                    .font(.system(size: 12))
                Spacer().frame(height: 48)
            }
        }
    }
}

// MARK: - Legacy full-window WebUI host (kept for diagnostics / remote-parity checks)

struct ARESWebView: View {
    @ObservedObject var serverManager = WebUIServerManager.shared
    @ObservedObject var config = ARESConfiguration.shared

    var body: some View {
        let host = WebUIServerManager.loopbackIfNetworkBind(config.webuiHost)
        if serverManager.isRunning {
            if let url = URL(string: "http://\(host):\(config.webuiPort)") {
                WebViewRepresentable(url: url, serverManager: serverManager)
            } else {
                Text("Invalid Server URL").foregroundColor(.red)
            }
        } else {
            ARESBootSplashView(status: serverManager.serverHealth)
        }
    }
}

struct WebViewRepresentable: NSViewRepresentable {
    let url: URL
    @ObservedObject var serverManager: WebUIServerManager

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.applicationNameForUserAgent = "ARES/1.0"
        // Authentication cookies and WebUI accessibility preferences must
        // survive a normal app restart. ARES does not register a service
        // worker, so the default persistent store cannot serve a stale
        // offline shell ahead of the app-managed FastAPI readiness check.
        config.websiteDataStore = WKWebsiteDataStore.default()
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator

        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {
        let isHealthy = serverManager.serverHealth == "Running (Healthy)"
            || serverManager.serverHealth == "Running (External)"
        if !isHealthy {
            context.coordinator.hasReloadedForHealthyServer = false
        } else if !context.coordinator.hasReloadedForHealthyServer {
            context.coordinator.hasReloadedForHealthyServer = true
            var request = URLRequest(url: url)
            request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
            nsView.load(request)
            return
        }

        if let currentURL = nsView.url, currentURL.host == url.host, currentURL.port == url.port {
            // Keep current page, do not reload
        } else {
            nsView.load(URLRequest(url: url))
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    class Coordinator: NSObject, WKNavigationDelegate {
        var parent: WebViewRepresentable
        var hasReloadedForHealthyServer = false

        init(_ parent: WebViewRepresentable) {
            self.parent = parent
        }

        private var pollingTimer: DispatchSourceTimer? = nil

        deinit {
            pollingTimer?.cancel()
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            showFallback(webView)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            showFallback(webView)
        }

        private func showFallback(_ webView: WKWebView) {
            let host = parent.url.host ?? "127.0.0.1"
            let port = parent.url.port ?? 8788
            let fallbackHTML = """
            <html><body style="background:#101014;color:#fff;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
            <div style="text-align:center">
            <h1 style="color:#d9b256;font-weight:300">ARES</h1>
            <p style="color:#888">Waiting for WebUI server to respond…</p>
            <p style="color:#555;font-size:12px">http://\(host):\(port)</p>
            </div></body></html>
            """
            webView.loadHTMLString(fallbackHTML, baseURL: parent.url)
            startPollingForRecovery(webView: webView)
        }

        private func startPollingForRecovery(webView: WKWebView) {
            pollingTimer?.cancel()
            
            let checkURL = self.parent.url.appendingPathComponent("health")
            let mainURL = self.parent.url
            
            let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.main)
            timer.schedule(deadline: .now(), repeating: 2.0)
            timer.setEventHandler { [weak self, weak webView] in
                guard let self = self, let webView = webView else { return }
                
                var request = URLRequest(url: checkURL)
                request.timeoutInterval = 1.0
                
                URLSession.shared.dataTask(with: request) { [weak self, weak webView] _, response, error in
                    if let httpResp = response as? HTTPURLResponse, httpResp.statusCode == 200 {
                        DispatchQueue.main.async {
                            guard let self = self, let webView = webView else { return }
                            self.pollingTimer?.cancel()
                            self.pollingTimer = nil
                            webView.load(URLRequest(url: mainURL))
                        }
                    }
                }.resume()
            }
            timer.resume()
            self.pollingTimer = timer
        }
    }
}

// MARK: - App Delegate

@MainActor
final class ARESAppDelegate: NSObject, NSApplicationDelegate {
    private var menuBarController: ARESMenuBarController?
    private let quickLaunchMonitor = ARESGlobalQuickLaunchMonitor()

    func applicationWillFinishLaunching(_ notification: Notification) {
        NSWindow.allowsAutomaticWindowTabbing = false
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // ARES lives in the menu bar. `.accessory` keeps it out of the Dock and
        // the app switcher; the status item is the entry point for opening the
        // window, controlling the controller process, and quitting.
        NSApp.setActivationPolicy(.accessory)

        ARESWindowCoordinator.shared.onWindowClosed = { [weak self] in
            self?.mainWindowDidClose()
        }

        // Reflect a controller that is already running (started by `ares
        // start`, ctl.sh/launchd, or a previous run of this app) before
        // anything can mistake it for a foreign process holding the port.
        Task { await WebUIServerManager.shared.adoptRunningControllerIfPresent() }

        NativeSystemBridge.shared.start(
            serverManager: WebUIServerManager.shared,
            applyMenuBar: { [weak self] enabled in
                self?.setMenuBarEnabled(enabled) ?? false
            },
            applyQuickLaunch: { [weak self] enabled, shortcut in
                guard let self else { return false }
                return self.quickLaunchMonitor.apply(enabled: enabled, shortcut: shortcut) { [weak self] in
                    self?.openMainWindow()
                }
            },
            applyBackgroundOperation: { enabled in
                // The app delegate reads this desired value when the window
                // closes. Returning it records the effective policy.
                enabled
            },
            restartServer: {
                Task { await WebUIServerManager.shared.restart() }
            }
        )

        if CommandLine.arguments.contains("--start-server") {
            Task {
                await WebUIServerManager.shared.start()
            }
        }

        // Lazy start default: Launch silently into the menu bar with the server
        // off. Only open the main window if explicitly requested via --open-window.
        if CommandLine.arguments.contains("--open-window") {
            ARESWindowCoordinator.shared.openMainWindow()
        }
    }

    func openMainWindow() {
        if !WebUIServerManager.shared.isRunning {
            Task { await WebUIServerManager.shared.start() }
        }
        ARESWindowCoordinator.shared.openMainWindow()
    }

    /// Closing the window is not quitting: the status item stays, and the
    /// controller keeps running unless the user turned background operation off.
    private func mainWindowDidClose() {
        guard !NativeSystemBridge.shared.desired.backgroundOperation else { return }
        Task { await WebUIServerManager.shared.stop() }
    }

    func applicationWillTerminate(_ notification: Notification) {
        NativeSystemBridge.shared.stop()
        quickLaunchMonitor.stop()
        Task { await WebUIServerManager.shared.stop() }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        // Re-launching from `ares`, Spotlight, or Finder while the app is
        // already in the menu bar is a request to see the window.
        openMainWindow()
        return true
    }

    private func setMenuBarEnabled(_ enabled: Bool) -> Bool {
        // The status item is the only way to reach a menu-bar-only ARES.
        // Honoring a request to hide it would strand the app with no entry
        // point, so it stays on and the effective value reports that.
        if menuBarController == nil {
            menuBarController = ARESMenuBarController()
        }
        return true
    }
}

// MARK: - Menu Bar

@MainActor
final class ARESMenuBarController: NSObject, NSMenuDelegate {
    private var statusItem: NSStatusItem?
    private var popover: NSPopover?
    private let menu = NSMenu()

    override init() {
        super.init()
        setupStatusItem()
    }

    private func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        let icon = NSImage(systemSymbolName: "shield", accessibilityDescription: "ARES")
            ?? NSImage(systemSymbolName: "gear", accessibilityDescription: "ARES")
        icon?.isTemplate = true
        item.button?.image = icon
        item.button?.target = self
        item.button?.action = #selector(statusItemClicked)
        // A status item that owns a `menu` swallows every click before the
        // button action runs. Leaving `menu` unset and attaching it only for
        // the duration of a left click is what lets right click reach the
        // status panel instead.
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        statusItem = item

        menu.delegate = self
        rebuildMenu()
    }

    func invalidate() {
        if let statusItem {
            NSStatusBar.system.removeStatusItem(statusItem)
        }
        statusItem = nil
        popover?.performClose(nil)
        popover = nil
    }

    // MARK: Click routing

    @objc private func statusItemClicked() {
        let event = NSApp.currentEvent
        let wantsPanel = event?.type == .rightMouseUp
            || event?.modifierFlags.contains(.control) == true
        if wantsPanel {
            showStatusPanel()
        } else {
            showMenu()
        }
    }

    private func showMenu() {
        guard let statusItem, let button = statusItem.button else { return }
        popover?.performClose(nil)
        statusItem.menu = menu
        button.performClick(nil)
        // Detaching the menu again restores button-action routing, so the next
        // right click still opens the panel.
        statusItem.menu = nil
    }

    @objc private func showStatusPanel() {
        guard let button = statusItem?.button else { return }
        if let popover, popover.isShown {
            popover.performClose(nil)
            return
        }
        let panel = NSPopover()
        panel.contentViewController = NSHostingController(rootView: MenuBarPopoverView())
        panel.behavior = .transient
        NSApp.activate(ignoringOtherApps: true)
        panel.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover = panel
    }

    // MARK: Menu

    /// Rebuilt on every open so server state, the address, and the quick
    /// settings checkmarks are never stale.
    func menuNeedsUpdate(_ menu: NSMenu) {
        rebuildMenu()
    }

    private func item(_ title: String, _ action: Selector?, _ key: String = "") -> NSMenuItem {
        // Items need an explicit target: with AppKit's auto-enabling, a
        // nil-target action resolves via the responder chain, this controller
        // is not in it, and every item renders permanently disabled.
        let entry = NSMenuItem(title: title, action: action, keyEquivalent: key)
        entry.target = self
        return entry
    }

    private func rebuildMenu() {
        let server = WebUIServerManager.shared
        let config = ARESConfiguration.shared
        let settings = NativeSystemBridge.shared.desired

        menu.removeAllItems()

        let header = NSMenuItem(title: "ARES Controller", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)

        let indicator = server.isRunning ? "\u{25CF}" : "\u{25CB}"
        let status = NSMenuItem(
            title: "\(indicator) \(server.serverHealth) \u{00B7} \(config.webuiHost):\(config.webuiPort)",
            action: nil,
            keyEquivalent: ""
        )
        status.isEnabled = false
        menu.addItem(status)

        menu.addItem(NSMenuItem.separator())
        menu.addItem(item("Open ARES", #selector(openWindow), "o"))
        menu.addItem(item("Open Web UI in Browser", #selector(openWebUI)))
        menu.addItem(item("Copy Web UI Address", #selector(copyWebUIAddress)))

        menu.addItem(NSMenuItem.separator())
        if server.isRunning {
            menu.addItem(item("Stop Server", #selector(stopServer)))
            menu.addItem(item("Restart Server", #selector(restartServer)))
        } else if server.conflictingStandaloneInstance {
            menu.addItem(item("Take Control & Restart", #selector(takeControlAndRestart)))
        } else {
            menu.addItem(item("Start Server", #selector(startServer)))
        }
        menu.addItem(item("Server Status\u{2026}", #selector(showStatusPanel)))

        let quickSettings = NSMenu()
        let launchAtLogin = item("Launch ARES at Login", #selector(toggleLaunchAtLogin))
        launchAtLogin.state = settings.launchAtLogin ? .on : .off
        quickSettings.addItem(launchAtLogin)

        let background = item("Keep Server Running in Background", #selector(toggleBackgroundOperation))
        background.state = settings.backgroundOperation ? .on : .off
        quickSettings.addItem(background)

        let quickLaunch = item("Global Quick Launch Shortcut", #selector(toggleQuickLaunch))
        quickLaunch.state = settings.quickLaunchEnabled ? .on : .off
        quickSettings.addItem(quickLaunch)

        let quickSettingsItem = NSMenuItem(title: "Quick Settings", action: nil, keyEquivalent: "")
        quickSettingsItem.submenu = quickSettings
        menu.addItem(quickSettingsItem)

        menu.addItem(NSMenuItem.separator())
        menu.addItem(item("Settings\u{2026}", #selector(openSettings), ","))
        menu.addItem(item("About ARES", #selector(showAbout)))

        menu.addItem(NSMenuItem.separator())
        menu.addItem(item("Quit ARES", #selector(terminate), "q"))
    }

    // MARK: Actions

    private var appDelegate: ARESAppDelegate? {
        NSApp.delegate as? ARESAppDelegate
    }

    @objc private func openWindow() {
        appDelegate?.openMainWindow()
    }

    @objc private func openWebUI() {
        guard let url = webUIURL() else { return }
        NSWorkspace.shared.open(url)
    }

    @objc private func copyWebUIAddress() {
        guard let url = webUIURL() else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url.absoluteString, forType: .string)
    }

    private func webUIURL() -> URL? {
        let config = ARESConfiguration.shared
        let host = WebUIServerManager.loopbackIfNetworkBind(config.webuiHost)
        return URL(string: "http://\(host):\(config.webuiPort)")
    }

    @objc private func startServer() {
        Task {
            await WebUIServerManager.shared.start()
        }
    }

    @objc private func stopServer() {
        Task { await WebUIServerManager.shared.stop() }
    }

    @objc private func restartServer() {
        Task {
            await WebUIServerManager.shared.restart()
        }
    }

    @objc private func takeControlAndRestart() {
        Task {
            await WebUIServerManager.shared.stopConflictingStandaloneInstance()
            if !WebUIServerManager.shared.portConflict {
                await WebUIServerManager.shared.start()
            }
        }
    }

    @objc private func toggleLaunchAtLogin() {
        NativeSystemBridge.shared.updateDesired { $0.launchAtLogin.toggle() }
    }

    @objc private func toggleBackgroundOperation() {
        NativeSystemBridge.shared.updateDesired { $0.backgroundOperation.toggle() }
    }

    @objc private func toggleQuickLaunch() {
        NativeSystemBridge.shared.updateDesired { $0.quickLaunchEnabled.toggle() }
    }

    @objc private func openSettings() {
        if #available(macOS 13.0, *) {
            NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
        } else {
            NSApp.sendAction(Selector(("showPreferencesWindow:")), to: nil, from: nil)
        }
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func showAbout() {
        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(nil)
    }

    @objc private func terminate() {
        NSApp.terminate(nil)
    }
}

// MARK: - System Resource Monitor

struct SystemResourceSnapshot {
    let usedMemoryGB: Double
    let totalMemoryGB: Double

    static func sample() -> SystemResourceSnapshot {
        let totalBytes = Double(ProcessInfo.processInfo.physicalMemory)
        var count = mach_msg_type_number_t(MemoryLayout<vm_statistics64_data_t>.size / MemoryLayout<integer_t>.size)
        var vmStat = vm_statistics64()
        let kr = withUnsafeMutablePointer(to: &vmStat) { ptr in
            ptr.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { intPtr in
                host_statistics64(mach_host_self(), HOST_VM_INFO64, intPtr, &count)
            }
        }
        var usedBytes = totalBytes * 0.35
        if kr == KERN_SUCCESS {
            let pageSize = Double(getpagesize())
            let active = Double(vmStat.active_count) * pageSize
            let wire = Double(vmStat.wire_count) * pageSize
            let compressed = Double(vmStat.compressor_page_count) * pageSize
            usedBytes = active + wire + compressed
        }
        return SystemResourceSnapshot(
            usedMemoryGB: max(0.5, usedBytes / (1024 * 1024 * 1024)),
            totalMemoryGB: max(1.0, totalBytes / (1024 * 1024 * 1024))
        )
    }
}

// MARK: - Menu Bar Popover

/// The right-click surface on the status item: live detail the flat menu
/// cannot show, without duplicating its actions.
struct MenuBarPopoverView: View {
    @ObservedObject var serverManager = WebUIServerManager.shared
    @ObservedObject var config = ARESConfiguration.shared

    private var statusColor: Color {
        if !serverManager.isRunning { return .secondary }
        return serverManager.serverHealth == "Running (Healthy)" ? .green : .orange
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image("ares-app-icon")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 32, height: 32)
                VStack(alignment: .leading, spacing: 2) {
                    Text("ARES Controller")
                        .font(.headline)
                    Text("http://\(config.webuiHost):\(config.webuiPort)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }

            HStack(spacing: 6) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 8, height: 8)
                Text(serverManager.serverHealth)
                    .font(.footnote)
            }

            // System & Host Telemetry
            let stats = SystemResourceSnapshot.sample()
            VStack(alignment: .leading, spacing: 6) {
                Text("SYSTEM HEALTH")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundColor(.secondary)
                HStack(spacing: 8) {
                    HStack(spacing: 4) {
                        Text("💾 RAM:")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.secondary)
                        Text(String(format: "%.1f / %.0f GB", stats.usedMemoryGB, stats.totalMemoryGB))
                            .font(.system(size: 11, weight: .bold))
                    }
                    Spacer()
                    HStack(spacing: 4) {
                        Text("🤖 AI Engine:")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.secondary)
                        Text(serverManager.isRunning ? "Ready" : "Idle")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundColor(serverManager.isRunning ? .green : .secondary)
                    }
                }
                .padding(8)
                .background(Color.secondary.opacity(0.1))
                .cornerRadius(6)
            }

            if !serverManager.recentLogs.isEmpty {
                Divider()
                Text("Recent log")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                ScrollView {
                    Text(logTail)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
                .frame(height: 84)
            }

            Divider()

            HStack {
                Button("Open ARES") {
                    (NSApp.delegate as? ARESAppDelegate)?.openMainWindow()
                }
                .buttonStyle(.borderedProminent)

                if serverManager.isRunning {
                    Button("Restart") {
                        Task { await serverManager.restart() }
                    }
                    .buttonStyle(.bordered)
                    Button("Stop") {
                        Task { await serverManager.stop() }
                    }
                    .buttonStyle(.bordered)
                } else if serverManager.conflictingStandaloneInstance {
                    // A controller is already running on this port and proved
                    // itself to be ARES's own (started outside this app, e.g.
                    // via `ares start`) — offer to take it over instead of
                    // leaving the user with no start/stop/restart control.
                    Button("Take Control & Restart") {
                        Task {
                            await serverManager.stopConflictingStandaloneInstance()
                            if !serverManager.portConflict {
                                await serverManager.start()
                            }
                        }
                    }
                    .buttonStyle(.bordered)
                } else {
                    Button("Start Server") {
                        Task { await serverManager.start() }
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
        .padding()
        .frame(width: 300)
    }

    private var logTail: String {
        serverManager.recentLogs
            .components(separatedBy: .newlines)
            .filter { !$0.isEmpty }
            .suffix(12)
            .joined(separator: "\n")
    }
}
