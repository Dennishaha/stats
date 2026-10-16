#!/usr/bin/env python3
"""Run CPU stress scheduling regressions with macOS Command Line Tools.

Compile the production stress test with a recording dispatch queue so no busy
loops run. This checks worker counts and start/stop behavior without relying on
the scheduler's nondeterministic choice of cores or requiring a full Xcode.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def declaration(source, start, end):
    return source.split(start, 1)[1].split(end, 1)[0]


def run():
    system = (ROOT / "Kit/plugins/SystemKit.swift").read_text()
    helpers = (ROOT / "Kit/helpers.swift").read_text()
    core_type = "public enum coreType" + declaration(
        system, "public enum coreType", "public struct model_s")
    cpu = "public struct cpu_s" + declaration(
        system, "public struct cpu_s", "public struct dimm_s")
    core = "public struct core_s" + declaration(
        system, "public struct core_s", "public struct cpu_s")
    stress = "public class CPUStressTest" + declaration(
        helpers, "public class CPUStressTest", "public class GPUStressTest")
    fixture = r'''
import Foundation
import Darwin

final class SystemKit {
    static let shared = SystemKit()
    var device = Device()
    struct Device { var info = Info() }
    struct Info { var cpu: cpu_s? }
}

// Record submissions, never execute the CPU-burning closures.
final class DispatchQueue {
    static var submissions: [DispatchWorkItem] = []
    static func global(qos: DispatchQoS.QoSClass) -> DispatchQueue { DispatchQueue() }
    func async(execute item: DispatchWorkItem) { Self.submissions.append(item) }
}
func OSMemoryBarrier() {}

func check(_ name: String, efficiency: Int32?, performance: Int32?, superCores: Int32?,
           expected: [Int], missingCPU: Bool = false) {
    var cpu = cpu_s()
    cpu.eCores = efficiency
    cpu.pCores = performance
    cpu.sCores = superCores
    SystemKit.shared.device.info.cpu = missingCPU ? nil : cpu
    for (index, type) in [coreType.efficiency, .performance, .super].enumerated() {
        DispatchQueue.submissions = []
        let test = CPUStressTest(type: type)
        test.start()
        precondition(DispatchQueue.submissions.count == expected[index], name)
        precondition(test.isRunning == (expected[index] > 0), "running state: " + name)
        test.start()
        precondition(DispatchQueue.submissions.count == expected[index], "duplicate start: " + name)
        test.stop()
        precondition(!test.isRunning, "stop: " + name)
        precondition(DispatchQueue.submissions.allSatisfy { $0.isCancelled }, "cancel: " + name)
        DispatchQueue.submissions = []
        test.start()
        precondition(DispatchQueue.submissions.count == expected[index], "restart: " + name)
        test.stop()
    }
    print("PASS: " + name)
}

check("M6 6E+4P+2S", efficiency: 6, performance: 4, superCores: 2, expected: [6, 6, 2])
check("M5 Pro 12P+6S", efficiency: 0, performance: 12, superCores: 6, expected: [0, 18, 6])
check("M5 6E+4S", efficiency: 6, performance: 0, superCores: 4, expected: [6, 0, 4])
check("S only", efficiency: 0, performance: 0, superCores: 8, expected: [0, 0, 8])
check("S with missing P/E counts", efficiency: nil, performance: nil, superCores: 8, expected: [0, 0, 8])
check("S+E with missing P count", efficiency: 6, performance: nil, superCores: 4, expected: [6, 0, 4])
check("M1 4E+4P", efficiency: 4, performance: 4, superCores: nil, expected: [4, 4, 0])
check("zero cores", efficiency: 0, performance: 0, superCores: 0, expected: [0, 0, 0])
check("missing counts", efficiency: nil, performance: nil, superCores: nil, expected: [2, 4, 0])
check("missing CPU", efficiency: nil, performance: nil, superCores: nil,
      expected: [2, 4, 0], missingCPU: true)
'''
    with tempfile.TemporaryDirectory(prefix="stats-cpu-stress-tests-") as directory:
        build = Path(directory)
        source = build / "main.swift"
        source.write_text(core_type + core + cpu + stress + fixture)
        executable = build / "tests"
        subprocess.run(["xcrun", "swiftc", "-swift-version", "5", str(source),
                        "-o", str(executable)], check=True, timeout=120)
        subprocess.run([str(executable)], check=True, timeout=30)


if __name__ == "__main__":
    run()
