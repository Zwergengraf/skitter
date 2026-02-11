// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SkittermanderMenuBar",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "SkittermanderMenuBar", targets: ["SkittermanderMenuBar"])
    ],
    dependencies: [
        .package(url: "https://github.com/argmaxinc/WhisperKit.git", from: "0.15.0")
    ],
    targets: [
        .executableTarget(
            name: "SkittermanderMenuBar",
            dependencies: [
                "WhisperKit"
            ],
            path: "Sources/SkittermanderMenuBar",
            swiftSettings: [
                // Keep Xcode Run (Debug) responsive while getting near-Release STT performance.
                .unsafeFlags(["-O"], .when(configuration: .debug))
            ]
        )
    ]
)
