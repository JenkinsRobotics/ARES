import SwiftUI
import AppKit
import Network
import AVFoundation
import Speech
import Contacts
import EventKit
import ARESCore
import CoreImage.CIFilterBuiltins

// MARK: - API Response Types

struct PendingApproval: Identifiable, Codable {
    var id: String { approval_id }
    let approval_id: String
    let session_id: String
    let tool_name: String
    let command: String
    let justification: String?
    let timestamp: String
}

struct ApprovalListResponse: Codable {
    let approvals: [PendingApproval]
}

struct AuditLogEntry: Identifiable, Codable {
    var id: String { "\(timestamp)_\(action)" }
    let timestamp: String
    let action: String
    let details: String
    let status: String
}

struct AuditLogResponse: Codable {
    let logs: [AuditLogEntry]
}

struct RuntimeConnectionOption: Identifiable, Codable {
    let id: String
    let name: String
    let kind: String
    let status: String
    let description: String?
}

struct RuntimeConnectionsResponse: Codable {
    let selected: String
    let connections: [RuntimeConnectionOption]
}

struct BackendSetResponse: Codable {
    let ok: Bool?
    let backend: String?
}

// MARK: - Main Settings View

public struct ARESSettingsView: View {
    @ObservedObject var config = ARESConfiguration.shared
    @ObservedObject var serverManager = WebUIServerManager.shared
    
    @State private var activeTab = 0
    
    // Remote Access
    @State private var lanIP: String? = nil
    @State private var tailscaleIP: String? = nil
    
    // Backends status
    @State private var activeBackend = UserDefaults.standard.string(forKey: "ares.backend.selected") ?? ""
    @State private var runtimeOptions: [RuntimeConnectionOption] = []
    @State private var backendSelectionError: String? = nil
    @State private var checkTimer: Timer? = nil
    
    // Safety & Approvals
    @State private var pendingApprovals: [PendingApproval] = []
    @State private var auditLogs: [AuditLogEntry] = []
    @State private var pathMonitor: NWPathMonitor? = nil
    @State private var permissionRefresh = 0
    @State private var copiedText: String? = nil
    
    public init() {}
    
    public var body: some View {
        VStack(spacing: 0) {
            // Top Navigation Tab Bar
            tabHeader
            
            Divider()
            
            // Tab Content
            ScrollView(.vertical, showsIndicators: true) {
                VStack(spacing: 16) {
                    switch activeTab {
                    case 0:
                        serverTab
                    case 1:
                        remoteAccessTab
                    case 2:
                        backendsTab
                    case 3:
                        safetyTab
                    case 4:
                        permissionsTab
                    default:
                        serverTab
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .top)
            }
        }
        .frame(minWidth: 720, minHeight: 560)
        .background(Color(NSColor.windowBackgroundColor))
        .preferredColorScheme(.dark)
        .onAppear {
            refreshNetworkIPs()
            refreshBackendSelection()
            startLivenessChecks()
            refreshApprovalsAndLogs()
            refreshPermissions()
            
            let monitor = NWPathMonitor()
            monitor.pathUpdateHandler = { _ in
                DispatchQueue.main.async {
                    self.refreshNetworkIPs()
                }
            }
            monitor.start(queue: .global())
            self.pathMonitor = monitor
        }
        .onDisappear {
            checkTimer?.invalidate()
            pathMonitor?.cancel()
        }
    }
    
    // MARK: - Tab Header Bar
    
    private var tabHeader: some View {
        HStack(spacing: 6) {
            tabButton(title: "Server & Network", icon: "server.rack", tag: 0)
            tabButton(title: "Remote Access", icon: "qrcode", tag: 1)
            tabButton(title: "Runtimes", icon: "cpu", tag: 2)
            tabButton(title: "Safety & Approvals", icon: "shield.checkered", tag: 3)
            tabButton(title: "Permissions", icon: "lock.shield", tag: 4)
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Color(NSColor.controlBackgroundColor).opacity(0.6))
    }
    
    private func tabButton(title: String, icon: String, tag: Int) -> some View {
        let isSelected = activeTab == tag
        return Button(action: {
            withAnimation(.easeInOut(duration: 0.15)) {
                activeTab = tag
            }
        }) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 13, weight: isSelected ? .semibold : .regular))
                Text(title)
                    .font(.system(size: 12, weight: isSelected ? .semibold : .regular))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .foregroundColor(isSelected ? .white : .secondary)
            .background(
                RoundedRectangle(cornerRadius: 7)
                    .fill(isSelected ? Color.accentColor.opacity(0.85) : Color.clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
    
    // MARK: - Card Container Helper
    
    private func settingsCard<Content: View>(title: String, icon: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .foregroundColor(.accentColor)
                    .font(.system(size: 14, weight: .semibold))
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundColor(.primary)
                Spacer()
            }
            
            content()
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(NSColor.controlBackgroundColor))
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color.white.opacity(0.08), lineWidth: 1)
                )
        )
    }

    // MARK: - Server & Network Tab
    
    private var serverTab: some View {
        VStack(spacing: 16) {
            // Card 1: Server Status & Controls
            settingsCard(title: "Web UI Server Status", icon: "waveform.path.ecg") {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 12) {
                        Circle()
                            .fill(serverColor)
                            .frame(width: 10, height: 10)
                            .shadow(color: serverColor.opacity(0.6), radius: 4)
                        
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Status: \(serverManager.serverHealth)")
                                .font(.system(size: 13, weight: .semibold))
                            
                            let host = WebUIServerManager.loopbackIfNetworkBind(config.webuiHost)
                            Text("Address: http://\(host):\(config.webuiPort)")
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(.secondary)
                        }
                        
                        Spacer()
                    }
                    .padding(10)
                    .background(Color.black.opacity(0.2))
                    .cornerRadius(8)
                    
                    HStack(spacing: 10) {
                        Button(action: {
                            Task { await serverManager.start() }
                        }) {
                            Label("Start Server", systemImage: "play.fill")
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.green)
                        .disabled(serverManager.isRunning || serverManager.conflictingStandaloneInstance)

                        Button(action: {
                            Task { await serverManager.stop() }
                        }) {
                            Label("Stop Server", systemImage: "stop.fill")
                        }
                        .buttonStyle(.bordered)
                        .tint(.red)
                        .disabled(!serverManager.isRunning)

                        Button(action: {
                            Task { await serverManager.restart() }
                        }) {
                            Label("Restart Server", systemImage: "arrow.clockwise")
                        }
                        .buttonStyle(.bordered)
                        .disabled(serverManager.conflictingStandaloneInstance)

                        if serverManager.conflictingStandaloneInstance {
                            Button("Take Control & Restart") {
                                Task {
                                    await serverManager.stopConflictingStandaloneInstance()
                                    if !serverManager.portConflict {
                                        await serverManager.start()
                                    }
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(.orange)
                        }
                        
                        Spacer()
                    }
                }
            }
            
            // Card 2: Network & Tailscale Binding
            settingsCard(title: "Network & Tailscale Binding", icon: "network") {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Choose which network interfaces the ARES Web UI server listens on:")
                        .font(.system(size: 12))
                        .foregroundColor(.secondary)
                    
                    HStack(spacing: 12) {
                        // Preset 1: Local Only
                        Button(action: {
                            config.webuiHost = "127.0.0.1"
                        }) {
                            HStack {
                                Image(systemName: config.webuiHost == "127.0.0.1" ? "checkmark.circle.fill" : "circle")
                                    .foregroundColor(config.webuiHost == "127.0.0.1" ? .accentColor : .secondary)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Local Only (127.0.0.1)")
                                        .font(.system(size: 12, weight: .semibold))
                                    Text("Private to this Mac only")
                                        .font(.system(size: 10))
                                        .foregroundColor(.secondary)
                                }
                            }
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(config.webuiHost == "127.0.0.1" ? Color.accentColor.opacity(0.15) : Color.black.opacity(0.15))
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 8)
                                            .stroke(config.webuiHost == "127.0.0.1" ? Color.accentColor : Color.white.opacity(0.06), lineWidth: 1)
                                    )
                            )
                        }
                        .buttonStyle(.plain)
                        
                        // Preset 2: Tailscale & LAN
                        Button(action: {
                            config.webuiHost = "0.0.0.0"
                            config.allowUnauthenticatedNetwork = true
                        }) {
                            HStack {
                                Image(systemName: config.webuiHost == "0.0.0.0" ? "checkmark.circle.fill" : "circle")
                                    .foregroundColor(config.webuiHost == "0.0.0.0" ? .accentColor : .secondary)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Tailscale & LAN (0.0.0.0)")
                                        .font(.system(size: 12, weight: .semibold))
                                    Text("Accessible across Tailnet & Wi-Fi")
                                        .font(.system(size: 10))
                                        .foregroundColor(.secondary)
                                }
                            }
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(config.webuiHost == "0.0.0.0" ? Color.accentColor.opacity(0.15) : Color.black.opacity(0.15))
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 8)
                                            .stroke(config.webuiHost == "0.0.0.0" ? Color.accentColor : Color.white.opacity(0.06), lineWidth: 1)
                                    )
                            )
                        }
                        .buttonStyle(.plain)
                    }
                    
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 10) {
                        GridRow {
                            Text("Host Address:")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(.secondary)
                                .gridColumnAlignment(.trailing)
                            TextField("0.0.0.0", text: $config.webuiHost)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 160)
                        }
                        GridRow {
                            Text("Port:")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(.secondary)
                                .gridColumnAlignment(.trailing)
                            TextField("8788", value: $config.webuiPort, formatter: NumberFormatter())
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 160)
                        }
                    }
                    
                    Divider().padding(.vertical, 2)
                    
                    VStack(alignment: .leading, spacing: 6) {
                        Toggle(isOn: $config.allowUnauthenticatedNetwork) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Allow Unauthenticated Network Access (Tailscale / LAN)")
                                    .font(.system(size: 12, weight: .semibold))
                                Text("Allows connecting from your phones, tablets, or laptops on Tailscale without blocking for password auth.")
                                    .font(.system(size: 11))
                                    .foregroundColor(.secondary)
                            }
                        }
                        .toggleStyle(.checkbox)
                        
                        Toggle(isOn: $config.reloadDevMode) {
                            Text("Enable Live Reload / Dev Mode")
                                .font(.system(size: 12))
                        }
                        .toggleStyle(.checkbox)
                        .padding(.top, 4)
                    }
                }
            }
            
            // Card 3: ARES Device Mesh
            settingsCard(title: "ARES Device Mesh & Node Role", icon: "circle.grid.cross") {
                VStack(alignment: .leading, spacing: 12) {
                    Picker("Role", selection: $config.aresRole) {
                        Text("Primary AI Body").tag("primary")
                        Text("Joined ARES Device").tag("device")
                    }
                    .pickerStyle(.segmented)
                    
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 10) {
                        GridRow {
                            Text("Device ID:")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(.secondary)
                                .gridColumnAlignment(.trailing)
                            TextField("Device ID", text: $config.aresDeviceID)
                                .textFieldStyle(.roundedBorder)
                        }
                        GridRow {
                            Text("AI ID:")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(.secondary)
                                .gridColumnAlignment(.trailing)
                            TextField("AI ID", text: $config.aresAIID)
                                .textFieldStyle(.roundedBorder)
                        }
                        if config.aresRole != "primary" {
                            GridRow {
                                Text("Primary ARES URL:")
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(.secondary)
                                    .gridColumnAlignment(.trailing)
                                TextField("http://...", text: $config.aresPrimaryURL)
                                    .textFieldStyle(.roundedBorder)
                            }
                        }
                        GridRow {
                            Text("Continuity Folder:")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(.secondary)
                                .gridColumnAlignment(.trailing)
                            TextField("/path/to/folder", text: $config.aresContinuityDir)
                                .textFieldStyle(.roundedBorder)
                        }
                    }
                    
                    Text(config.aresRole == "primary"
                         ? "This Mac owns the canonical ARES identity and device registry."
                         : "This Mac joins an existing AI and contributes local tools and compute.")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                }
            }
            
            // Card 4: Paths & Diagnostics
            settingsCard(title: "Storage Paths & Diagnostics", icon: "folder") {
                VStack(alignment: .leading, spacing: 10) {
                    pathRow(label: "Config Directory", path: "~/.ares")
                    pathRow(label: "State Database", path: "~/.ares/state.db")
                    pathRow(label: "Logs File", path: "~/.ares/webui.log")
                }
            }
        }
    }
    
    private func pathRow(label: String, path: String) -> some View {
        HStack {
            Text("\(label):")
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(.secondary)
                .frame(width: 110, alignment: .leading)
            
            Text(path)
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(.primary)
            
            Spacer()
            
            Button(action: {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(path, forType: .string)
            }) {
                Image(systemName: "doc.on.doc")
                    .font(.system(size: 11))
            }
            .buttonStyle(.plain)
            .foregroundColor(.secondary)
            .help("Copy path to clipboard")
        }
        .padding(6)
        .background(Color.black.opacity(0.15))
        .cornerRadius(6)
    }
    
    // MARK: - Remote Access Tab
    
    private var remoteAccessTab: some View {
        VStack(spacing: 16) {
            settingsCard(title: "Mobile & Tablet Connection", icon: "qrcode") {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top, spacing: 24) {
                        // QR Code
                        VStack(spacing: 8) {
                            if let url = qrCodeURL, let qrImage = generateQRCode(from: url) {
                                Image(nsImage: qrImage)
                                    .resizable()
                                    .interpolation(.none)
                                    .frame(width: 140, height: 140)
                                    .padding(8)
                                    .background(Color.white)
                                    .cornerRadius(10)
                                    .shadow(radius: 3)
                                Text("Scan with iPhone/iPad")
                                    .font(.system(size: 11, weight: .medium))
                                    .foregroundColor(.secondary)
                            } else {
                                VStack(spacing: 6) {
                                    Image(systemName: "qrcode.viewfinder")
                                        .font(.system(size: 64))
                                        .foregroundColor(.secondary)
                                    Text("Start server to generate QR")
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)
                                }
                                .frame(width: 156, height: 156)
                                .background(Color.black.opacity(0.2))
                                .cornerRadius(10)
                            }
                        }
                        
                        // Addresses list
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Accessible URLs:")
                                .font(.system(size: 12, weight: .semibold))
                            
                            let localHost = WebUIServerManager.loopbackIfNetworkBind(config.webuiHost)
                            urlChip(label: "Localhost", url: "http://\(localHost):\(config.webuiPort)")
                            
                            if let lan = lanIP {
                                urlChip(label: "Wi-Fi / LAN", url: "http://\(lan):\(config.webuiPort)")
                            } else {
                                chipPlaceholder(label: "Wi-Fi / LAN", text: "Not connected to local network")
                            }
                            
                            if let ts = tailscaleIP {
                                urlChip(label: "Tailscale", url: "http://\(ts):\(config.webuiPort)")
                            } else {
                                chipPlaceholder(label: "Tailscale", text: "Tailscale IP not detected")
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    
                    Divider()
                    
                    // Quick setup
                    VStack(alignment: .leading, spacing: 8) {
                        Text("One-Click Network Setup")
                            .font(.system(size: 12, weight: .semibold))
                        
                        HStack(spacing: 12) {
                            Button(action: {
                                config.webuiHost = "0.0.0.0"
                                config.allowUnauthenticatedNetwork = true
                                Task { await serverManager.restart() }
                            }) {
                                Label("Enable Tailscale & LAN (0.0.0.0)", systemImage: "network")
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(config.webuiHost == "0.0.0.0" ? .green : .accentColor)

                            Button(action: {
                                config.webuiHost = "127.0.0.1"
                                Task { await serverManager.restart() }
                            }) {
                                Label("Local Only (127.0.0.1)", systemImage: "lock.laptopcomputer")
                            }
                            .buttonStyle(.bordered)
                            .tint(config.webuiHost == "127.0.0.1" ? .green : .secondary)
                        }
                    }
                }
            }
            
            // Microphone warning card
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Image(systemName: "mic.slash.fill")
                        .foregroundColor(.orange)
                    Text("Microphone Browser Constraint")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundColor(.orange)
                }
                Text("Modern browsers (iOS Safari, Chrome) block microphone recording on unencrypted HTTP connections. When accessing from mobile over HTTP, voice input is disabled by the browser. To use voice, run locally or use HTTPS.")
                    .font(.system(size: 11))
                    .foregroundColor(.secondary)
                    .lineLimit(nil)
            }
            .padding(14)
            .background(Color.orange.opacity(0.08))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.orange.opacity(0.2), lineWidth: 1)
            )
            .cornerRadius(8)
        }
    }
    
    private func urlChip(label: String, url: String) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(.secondary)
                .frame(width: 75, alignment: .leading)
            
            Text(url)
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(.accentColor)
                .lineLimit(1)
            
            Spacer()
            
            Button(action: {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(url, forType: .string)
            }) {
                Image(systemName: "doc.on.doc")
                    .font(.system(size: 11))
            }
            .buttonStyle(.plain)
            .foregroundColor(.secondary)
            .help("Copy URL")
        }
        .padding(6)
        .background(Color.black.opacity(0.2))
        .cornerRadius(6)
    }
    
    private func chipPlaceholder(label: String, text: String) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(.secondary)
                .frame(width: 75, alignment: .leading)
            
            Text(text)
                .font(.system(size: 11))
                .foregroundColor(.secondary)
            
            Spacer()
        }
        .padding(6)
        .background(Color.black.opacity(0.1))
        .cornerRadius(6)
    }

    // MARK: - Backends Tab
    
    private var backendsTab: some View {
        VStack(spacing: 16) {
            settingsCard(title: "Default Chat Runtime", icon: "cpu") {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Select the default runtime execution backend for conversation turns:")
                        .font(.system(size: 12))
                        .foregroundColor(.secondary)
                    
                    if !serverManager.isRunning {
                        HStack(spacing: 8) {
                            Image(systemName: "info.circle")
                                .foregroundColor(.secondary)
                            Text("Start the server to inspect active runtimes and change backend.")
                                .font(.system(size: 11))
                                .foregroundColor(.secondary)
                        }
                        .padding(10)
                        .background(Color.black.opacity(0.2))
                        .cornerRadius(6)
                    } else if runtimeOptions.isEmpty {
                        Text("No external runtime backends registered.")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    } else {
                        VStack(spacing: 8) {
                            ForEach(runtimeOptions.filter { $0.kind == "runtime" }) { runtime in
                                Button(action: {
                                    writeBackendSelection(runtime.id)
                                }) {
                                    HStack {
                                        Image(systemName: activeBackend == runtime.id ? "checkmark.circle.fill" : "circle")
                                            .foregroundColor(activeBackend == runtime.id ? .accentColor : .secondary)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(runtime.name)
                                                .font(.system(size: 12, weight: .semibold))
                                            if let desc = runtime.description {
                                                Text(desc)
                                                    .font(.system(size: 10))
                                                    .foregroundColor(.secondary)
                                            }
                                        }
                                        Spacer()
                                        Text(runtime.status.capitalized)
                                            .font(.system(size: 10, weight: .semibold))
                                            .foregroundColor(.green)
                                    }
                                    .padding(10)
                                    .background(
                                        RoundedRectangle(cornerRadius: 8)
                                            .fill(activeBackend == runtime.id ? Color.accentColor.opacity(0.12) : Color.black.opacity(0.15))
                                            .overlay(
                                                RoundedRectangle(cornerRadius: 8)
                                                    .stroke(activeBackend == runtime.id ? Color.accentColor : Color.white.opacity(0.06), lineWidth: 1)
                                            )
                                    )
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    
                    if let backendSelectionError {
                        Text(backendSelectionError)
                            .font(.system(size: 11))
                            .foregroundColor(.red)
                    }
                }
            }
        }
    }

    // MARK: - Safety & Approvals Tab
    
    private var safetyTab: some View {
        VStack(spacing: 16) {
            settingsCard(title: "Pending Risk Approvals", icon: "shield.lefthalf.filled") {
                VStack(alignment: .leading, spacing: 10) {
                    if pendingApprovals.isEmpty {
                        HStack(spacing: 10) {
                            Image(systemName: "checkmark.shield.fill")
                                .font(.system(size: 24))
                                .foregroundColor(.green)
                            Text("No pending risk actions requiring approval.")
                                .font(.system(size: 12))
                                .foregroundColor(.secondary)
                        }
                        .frame(maxWidth: .infinity, minHeight: 60)
                        .background(Color.black.opacity(0.15))
                        .cornerRadius(8)
                    } else {
                        VStack(spacing: 8) {
                            ForEach(pendingApprovals) { app in
                                HStack {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(app.tool_name.isEmpty ? "System Tool" : app.tool_name)
                                            .font(.system(size: 12, weight: .semibold))
                                        Text(app.command)
                                            .font(.system(size: 10, design: .monospaced))
                                            .foregroundColor(.secondary)
                                    }
                                    Spacer()
                                    HStack(spacing: 8) {
                                        Button("Approve") {
                                            respondToApproval(app, choice: "once")
                                        }
                                        .buttonStyle(.borderedProminent)
                                        .tint(.green)
                                        
                                        Button("Deny") {
                                            respondToApproval(app, choice: "deny")
                                        }
                                        .buttonStyle(.bordered)
                                        .tint(.red)
                                    }
                                }
                                .padding(10)
                                .background(Color.black.opacity(0.2))
                                .cornerRadius(6)
                            }
                        }
                    }
                }
            }
            
            settingsCard(title: "Security Audit Logs", icon: "list.bullet.rectangle") {
                VStack(alignment: .leading, spacing: 8) {
                    if auditLogs.isEmpty {
                        Text("No audit events logged yet.")
                            .font(.system(size: 11))
                            .foregroundColor(.secondary)
                            .frame(maxWidth: .infinity, minHeight: 40)
                    } else {
                        VStack(spacing: 4) {
                            ForEach(auditLogs) { entry in
                                HStack {
                                    Text(formatTime(entry.timestamp))
                                        .font(.system(size: 10, design: .monospaced))
                                        .foregroundColor(.secondary)
                                        .frame(width: 60, alignment: .leading)
                                    Text(entry.action)
                                        .font(.system(size: 11, weight: .bold))
                                    Text(entry.details)
                                        .font(.system(size: 11))
                                        .lineLimit(1)
                                    Spacer()
                                    Text(entry.status.uppercased())
                                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                                        .foregroundColor(entry.status == "deny" ? .red : .green)
                                }
                                .padding(6)
                                .background(Color.black.opacity(0.15))
                                .cornerRadius(4)
                            }
                        }
                    }
                    
                    Button(action: {
                        refreshApprovalsAndLogs()
                    }) {
                        Label("Refresh Logs", systemImage: "arrow.clockwise")
                            .font(.system(size: 11))
                    }
                    .buttonStyle(.borderless)
                    .padding(.top, 4)
                }
            }
        }
    }

    // MARK: - Permissions Tab
    
    private struct PermissionRow: Identifiable {
        let id: String
        let title: String
        let detail: String
        let granted: Bool?
        let settingsAnchor: String
    }

    private var permissionsTab: some View {
        let rows = nativePermissionRows
        return settingsCard(title: "macOS Privacy & Capabilities", icon: "lock.shield") {
            VStack(alignment: .leading, spacing: 12) {
                Text("Read-only status of system permissions used by native macOS tools:")
                    .font(.system(size: 12))
                    .foregroundColor(.secondary)
                
                VStack(spacing: 6) {
                    ForEach(rows) { row in
                        HStack(spacing: 12) {
                            Image(systemName: permissionSymbol(row.granted))
                                .foregroundColor(permissionColor(row.granted))
                                .frame(width: 18)
                            
                            VStack(alignment: .leading, spacing: 2) {
                                Text(row.title)
                                    .font(.system(size: 12, weight: .semibold))
                                Text(row.detail)
                                    .font(.system(size: 10))
                                    .foregroundColor(.secondary)
                            }
                            
                            Spacer()
                            
                            Text(permissionLabel(row.granted))
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundColor(permissionColor(row.granted))
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(permissionColor(row.granted).opacity(0.15))
                                .cornerRadius(4)
                            
                            Button("Settings") {
                                openPrivacySettings(anchor: row.settingsAnchor)
                            }
                            .buttonStyle(.borderless)
                            .font(.system(size: 11))
                            .foregroundColor(.accentColor)
                        }
                        .padding(8)
                        .background(Color.black.opacity(0.15))
                        .cornerRadius(6)
                    }
                }
                .id(permissionRefresh)
                
                Button(action: {
                    refreshPermissions()
                }) {
                    Label("Refresh Permissions", systemImage: "arrow.clockwise")
                        .font(.system(size: 11))
                }
                .buttonStyle(.borderless)
                .padding(.top, 4)
            }
        }
    }

    private var nativePermissionRows: [PermissionRow] {
        let accessibility = AXIsProcessTrusted()
        let screenCapture = CGPreflightScreenCaptureAccess()
        let contacts = CNContactStore.authorizationStatus(for: .contacts)
        let calendars = EKEventStore.authorizationStatus(for: .event)
        let reminders = EKEventStore.authorizationStatus(for: .reminder)
        let microphone = AVCaptureDevice.authorizationStatus(for: .audio)
        let speech = SFSpeechRecognizer.authorizationStatus()
        return [
            PermissionRow(id: "accessibility", title: "Accessibility", detail: "Screen context and approved app automation.", granted: accessibility, settingsAnchor: "Privacy_Accessibility"),
            PermissionRow(id: "screen", title: "Screen Recording", detail: "Window titles and visible-screen context.", granted: screenCapture, settingsAnchor: "Privacy_ScreenCapture"),
            PermissionRow(id: "contacts", title: "Contacts", detail: "Search and manage contacts through native tools.", granted: authorizationGranted(contacts), settingsAnchor: "Privacy_Contacts"),
            PermissionRow(id: "calendars", title: "Calendars", detail: "Read and create calendar events.", granted: eventAuthorizationGranted(calendars), settingsAnchor: "Privacy_Calendars"),
            PermissionRow(id: "reminders", title: "Reminders", detail: "Read and manage reminders.", granted: eventAuthorizationGranted(reminders), settingsAnchor: "Privacy_Reminders"),
            PermissionRow(id: "microphone", title: "Microphone", detail: "Voice input in the native app.", granted: mediaAuthorizationGranted(microphone), settingsAnchor: "Privacy_Microphone"),
            PermissionRow(id: "speech", title: "Speech Recognition", detail: "Convert native voice input to text.", granted: speechAuthorizationGranted(speech), settingsAnchor: "Privacy_SpeechRecognition"),
            PermissionRow(id: "automation", title: "Apple Events / Notes", detail: "Requested by macOS when Notes automation first runs.", granted: nil, settingsAnchor: "Privacy_Automation"),
        ]
    }

    private func refreshPermissions() { permissionRefresh += 1 }

    private func openPrivacySettings(anchor: String) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)") {
            NSWorkspace.shared.open(url)
        }
    }

    private func permissionLabel(_ granted: Bool?) -> String {
        guard let granted else { return "On first use" }
        return granted ? "Granted" : "Not granted"
    }

    private func permissionSymbol(_ granted: Bool?) -> String {
        guard let granted else { return "questionmark.circle" }
        return granted ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
    }

    private func permissionColor(_ granted: Bool?) -> Color {
        guard let granted else { return .secondary }
        return granted ? .green : .orange
    }

    private func authorizationGranted(_ status: CNAuthorizationStatus) -> Bool {
        status == .authorized
    }

    private func eventAuthorizationGranted(_ status: EKAuthorizationStatus) -> Bool {
        status == .fullAccess || status == .writeOnly
    }

    private func mediaAuthorizationGranted(_ status: AVAuthorizationStatus) -> Bool {
        status == .authorized
    }

    private func speechAuthorizationGranted(_ status: SFSpeechRecognizerAuthorizationStatus) -> Bool {
        status == .authorized
    }

    // MARK: - Helpers
    
    private var serverColor: Color {
        switch serverManager.serverHealth {
        case "Running (Healthy)": return .green
        case "Starting...": return .orange
        case "Stopped": return .gray
        default: return .red
        }
    }
    
    private var qrCodeURL: String? {
        if let lan = lanIP {
            return "http://\(lan):\(config.webuiPort)"
        }
        return nil
    }
    
    private func generateQRCode(from string: String) -> NSImage? {
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)

        if let outputImage = filter.outputImage {
            let transform = CGAffineTransform(scaleX: 10, y: 10)
            let scaledImage = outputImage.transformed(by: transform)
            
            if let cgImage = context.createCGImage(scaledImage, from: scaledImage.extent) {
                return NSImage(cgImage: cgImage, size: NSSize(width: 160, height: 160))
            }
        }
        return nil
    }
    
    private func refreshNetworkIPs() {
        var lanAddress: String? = nil
        var tailscaleAddress: String? = nil

        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0 else { return }
        defer { freeifaddrs(ifaddr) }

        var ptr = ifaddr
        while ptr != nil {
            defer { ptr = ptr?.pointee.ifa_next }

            guard let interface = ptr?.pointee,
                  let interfaceAddr = interface.ifa_addr else { continue }
            let addrFamily = interfaceAddr.pointee.sa_family
            if addrFamily == UInt8(AF_INET) {
                let name = String(cString: interface.ifa_name)
                
                var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                getnameinfo(interfaceAddr, socklen_t(interfaceAddr.pointee.sa_len),
                            &hostname, socklen_t(hostname.count),
                            nil, 0, NI_NUMERICHOST)
                let ipAddress = String(
                    decoding: hostname.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) },
                    as: UTF8.self
                )
                
                if name.contains("utun") {
                    if ipAddress.hasPrefix("100.") {
                        tailscaleAddress = ipAddress
                    }
                } else if name.hasPrefix("en") || name.hasPrefix("ap") {
                    if !ipAddress.hasPrefix("127.") && !ipAddress.hasPrefix("169.254") {
                        lanAddress = ipAddress
                    }
                }
            }
        }
        self.lanIP = lanAddress
        self.tailscaleIP = tailscaleAddress
    }
    
    private func startLivenessChecks() {
        checkTimer = Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { _ in
            Task { @MainActor in
                refreshBackendSelection()
                refreshApprovalsAndLogs()
            }
        }
        refreshBackendSelection()
    }
    
    private func refreshApprovalsAndLogs() {
        guard serverManager.isRunning else {
            self.pendingApprovals = []
            self.auditLogs = []
            return
        }
        
        let host = WebUIServerManager.loopbackIfNetworkBind(config.webuiHost)
        let port = config.webuiPort
        
        // Fetch Approvals
        guard let approvalsUrl = URL(string: "http://\(host):\(port)/api/ares/approvals/pending") else { return }
        URLSession.shared.dataTask(with: approvalsUrl) { data, _, error in
            if let data = data, let decoded = try? JSONDecoder().decode(ApprovalListResponse.self, from: data) {
                DispatchQueue.main.async {
                    self.pendingApprovals = decoded.approvals
                }
            }
        }.resume()
        
        // Fetch Logs
        guard let logsUrl = URL(string: "http://\(host):\(port)/api/ares/audit/logs") else { return }
        URLSession.shared.dataTask(with: logsUrl) { data, _, error in
            if let data = data, let decoded = try? JSONDecoder().decode(AuditLogResponse.self, from: data) {
                DispatchQueue.main.async {
                    self.auditLogs = decoded.logs
                }
            }
        }.resume()
    }
    
    private func respondToApproval(_ app: PendingApproval, choice: String) {
        let host = WebUIServerManager.loopbackIfNetworkBind(config.webuiHost)
        let port = config.webuiPort
        
        guard let url = URL(string: "http://\(host):\(port)/api/approval/respond") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let body: [String: String] = [
            "session_id": app.session_id,
            "approval_id": app.approval_id,
            "choice": choice
        ]
        
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        
        URLSession.shared.dataTask(with: request) { _, _, _ in
            DispatchQueue.main.async {
                refreshApprovalsAndLogs()
            }
        }.resume()
    }
    
    private func writeBackendSelection(_ val: String) {
        let host = WebUIServerManager.loopbackIfNetworkBind(config.webuiHost)
        let port = config.webuiPort
        let previous = activeBackend
        activeBackend = val
        backendSelectionError = nil
        
        guard let url = URL(string: "http://\(host):\(port)/api/ares/backend/set") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let body = ["backend": val]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        
        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let error {
                    activeBackend = previous
                    backendSelectionError = "Failed to save default runtime: \(error.localizedDescription)"
                    return
                }
                guard let http = response as? HTTPURLResponse,
                      (200..<300).contains(http.statusCode) else {
                    activeBackend = previous
                    backendSelectionError = "Failed to save default runtime."
                    return
                }
                if let data,
                   let decoded = try? JSONDecoder().decode(BackendSetResponse.self, from: data),
                   decoded.ok == false {
                    activeBackend = previous
                    backendSelectionError = "Failed to save default runtime."
                    return
                }
                let confirmed = (data.flatMap { try? JSONDecoder().decode(BackendSetResponse.self, from: $0) }?.backend) ?? val
                activeBackend = confirmed
                UserDefaults.standard.set(confirmed, forKey: "ares.backend.selected")
            }
        }.resume()
    }

    private func refreshBackendSelection() {
        guard serverManager.isRunning else { return }
        let host = WebUIServerManager.loopbackIfNetworkBind(config.webuiHost)
        let port = config.webuiPort
        guard let url = URL(string: "http://\(host):\(port)/api/connections") else { return }

        URLSession.shared.dataTask(with: url) { data, _, _ in
            if let data,
               let decoded = try? JSONDecoder().decode(RuntimeConnectionsResponse.self, from: data) {
                DispatchQueue.main.async {
                    runtimeOptions = decoded.connections.filter { $0.kind == "runtime" }
                    activeBackend = decoded.selected
                    UserDefaults.standard.set(decoded.selected, forKey: "ares.backend.selected")
                }
            }
        }.resume()
    }
    
    private func formatTime(_ raw: String) -> String {
        if let idx = raw.firstIndex(of: "T") {
            let start = raw.index(after: idx)
            let end = raw.index(start, offsetBy: 8, limitedBy: raw.endIndex) ?? raw.endIndex
            return String(raw[start..<end])
        }
        return raw
    }
}
