// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SkitterMenuBar",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "SkitterMenuBar", targets: ["SkitterMenuBar"])
    ],
    dependencies: [],
    targets: [
        .executableTarget(
            name: "SkitterMenuBar",
            dependencies: [],
            path: "Sources/SkitterMenuBar",
            swiftSettings: [
                // Keep Xcode Run (Debug) responsive while getting near-Release STT performance.
                .unsafeFlags(["-O"], .when(configuration: .debug))
            ]
        )
    ]
)
