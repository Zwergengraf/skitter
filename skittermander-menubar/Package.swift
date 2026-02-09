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
    targets: [
        .executableTarget(
            name: "SkittermanderMenuBar",
            path: "Sources/SkittermanderMenuBar"
        )
    ]
)
