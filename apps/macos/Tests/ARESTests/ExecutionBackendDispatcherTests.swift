import XCTest
@testable import ARESCore

private final class FakeBackend: AgenticFrameworkBackend, @unchecked Sendable {
    let identifier: String
    let kind: ExecutionBackendKind
    let displayName: String
    let capabilities: Set<ExecutionCapability>
    var health: ExecutionBackendHealth
    private(set) var executeCount = 0
    let responseText: String

    init(
        kind: ExecutionBackendKind,
        capabilities: Set<ExecutionCapability>,
        health: ExecutionBackendHealth = ExecutionBackendHealth(state: .healthy),
        responseText: String = "ok"
    ) {
        self.identifier = "fake-\(kind.rawValue)"
        self.kind = kind
        self.displayName = "Fake \(kind.rawValue)"
        self.capabilities = capabilities
        self.health = health
        self.responseText = responseText
    }

    func healthCheck() async -> ExecutionBackendHealth { health }

    func execute(_ request: ExecutionRequest) async throws -> ExecutionResult {
        executeCount += 1
        return ExecutionResult(requestId: request.id, backend: kind, text: responseText)
    }
}

final class ExecutionBackendDispatcherTests: XCTestCase {
    private func request(_ caps: Set<ExecutionCapability>) -> ExecutionRequest {
        ExecutionRequest(
            userIntent: "do a thing",
            context: ConversationContext(conversationId: UUID(), workingDirectory: "/tmp"),
            requiredCapabilities: caps
        )
    }

    func testDispatchExecutesSelectedBackend() async throws {
        let jaeger = FakeBackend(kind: .jaeger, capabilities: [.agentTurn, .toolUse], responseText: "from-jaeger")
        let dispatcher = ExecutionBackendDispatcher(backends: [jaeger])

        let result = try await dispatcher.dispatch(request([.agentTurn]))

        XCTAssertEqual(result.text, "from-jaeger")
        XCTAssertEqual(result.backend, .jaeger)
        XCTAssertEqual(jaeger.executeCount, 1)
        // Routing provenance is preserved on the result.
        XCTAssertEqual(result.metadata["route_mode"], .string("single:jaeger"))
    }

    func testUnroutableWhenNoBackendCoversCapability() async throws {
        let jaeger = FakeBackend(kind: .jaeger, capabilities: [.agentTurn])
        let dispatcher = ExecutionBackendDispatcher(backends: [jaeger])

        do {
            _ = try await dispatcher.dispatch(request([.vision]))
            XCTFail("expected unroutable")
        } catch let ExecutionDispatchError.unroutable(missing, _) {
            XCTAssertEqual(missing, [.vision])
            XCTAssertEqual(jaeger.executeCount, 0)
        }
    }

    func testUnhealthyBackendIsNotDispatched() async throws {
        let down = FakeBackend(
            kind: .jaeger,
            capabilities: [.agentTurn],
            health: ExecutionBackendHealth(state: .unavailable)
        )
        let dispatcher = ExecutionBackendDispatcher(backends: [down])

        do {
            _ = try await dispatcher.dispatch(request([.agentTurn]))
            XCTFail("expected unroutable due to unhealthy backend")
        } catch ExecutionDispatchError.unroutable {
            XCTAssertEqual(down.executeCount, 0)
        }
    }

    func testPrefersHealthyBackendForCapability() async throws {
        let jaeger = FakeBackend(kind: .jaeger, capabilities: [.agentTurn], responseText: "jaeger")
        let cloud = FakeBackend(kind: .cloudProvider, capabilities: [.agentTurn], responseText: "cloud")
        // Registration order is product policy: the first healthy match wins a tie.
        let dispatcher = ExecutionBackendDispatcher(backends: [jaeger, cloud])

        let result = try await dispatcher.dispatch(request([.agentTurn]))
        XCTAssertEqual(result.text, "jaeger")
        XCTAssertEqual(jaeger.executeCount, 1)
        XCTAssertEqual(cloud.executeCount, 0)
    }
}
