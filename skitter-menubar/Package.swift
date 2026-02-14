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
    dependencies: [
        .package(url: "https://github.com/argmaxinc/WhisperKit.git", from: "0.15.0")
    ],
    targets: [
        .executableTarget(
            name: "SkitterMenuBar",
            dependencies: [
                "WhisperKit"
            ],
            path: "Sources/SkitterMenuBar",
            swiftSettings: [
                // Keep Xcode Run (Debug) responsive while getting near-Release STT performance.
                .unsafeFlags(["-O"], .when(configuration: .debug))
            ]
        )
    ]
)
