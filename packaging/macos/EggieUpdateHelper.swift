import AppKit
import CryptoKit
import Darwin
import Foundation
import Security

struct Failure: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

let files = FileManager.default

func pump(_ seconds: TimeInterval) {
    let end = Date().addingTimeInterval(seconds)
    if progress == nil { RunLoop.current.run(until: end); return }
    repeat {
        if let event = NSApplication.shared.nextEvent(matching: .any, until: end, inMode: .default, dequeue: true) {
            NSApplication.shared.sendEvent(event)
        }
        NSApplication.shared.updateWindows()
    } while Date() < end
}

let showNotification = Notification.Name("com.huang.eggie.update.show")

func progressLockURL(_ app: URL) -> URL {
    let hash = SHA256.hash(data: Data(app.path.utf8)).map { String(format: "%02x", $0) }.joined()
    return app.deletingLastPathComponent().appendingPathComponent(".eggie-progress-" + hash + ".lock")
}

final class ProgressWindow: NSObject {
    let window: NSWindow
    let title = NSTextField(labelWithString: "正在更新 Eggie")
    let stage = NSTextField(labelWithString: "准备更新")
    let detail = NSTextField(wrappingLabelWithString: "完成后会自动打开，请勿重复启动。")
    let spinner = NSProgressIndicator()
    let closeButton = NSButton(title: "关闭", target: nil, action: nil)
    var closed = false
    var observer: NSObjectProtocol?

    init(app: URL) {
        let application = NSApplication.shared
        application.setActivationPolicy(.accessory)
        application.finishLaunching()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 452, height: 208),
                          styleMask: [.titled], backing: .buffered, defer: false)
        super.init()
        window.title = "Eggie 软件更新"
        window.isReleasedWhenClosed = false
        title.font = .systemFont(ofSize: 20, weight: .semibold)
        stage.font = .systemFont(ofSize: 14, weight: .medium)
        detail.font = .systemFont(ofSize: 13)
        detail.textColor = .secondaryLabelColor
        detail.maximumNumberOfLines = 4
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.startAnimation(nil)
        closeButton.target = self
        closeButton.action = #selector(closeResult)
        closeButton.isHidden = true
        let row = NSStackView(views: [spinner, stage])
        row.orientation = .horizontal
        row.spacing = 10
        let content = window.contentView!
        for view in [title, row, detail, closeButton] {
            view.translatesAutoresizingMaskIntoConstraints = false
            content.addSubview(view)
        }
        NSLayoutConstraint.activate([
            title.topAnchor.constraint(equalTo: content.topAnchor, constant: 24),
            title.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            title.trailingAnchor.constraint(lessThanOrEqualTo: content.trailingAnchor, constant: -28),
            row.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 20),
            row.leadingAnchor.constraint(equalTo: title.leadingAnchor),
            row.trailingAnchor.constraint(lessThanOrEqualTo: content.trailingAnchor, constant: -28),
            detail.topAnchor.constraint(equalTo: row.bottomAnchor, constant: 14),
            detail.leadingAnchor.constraint(equalTo: title.leadingAnchor),
            detail.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            closeButton.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24),
            closeButton.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -16),
            closeButton.widthAnchor.constraint(equalToConstant: 78),
        ])
        observer = DistributedNotificationCenter.default().addObserver(
            forName: showNotification, object: app.path, queue: .main) { [weak self] _ in self?.bringForward() }
        window.center()
        bringForward()
        window.displayIfNeeded()
        pump(0.1)
    }

    func bringForward() {
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    func phase(_ text: String) { stage.stringValue = text; pump(0.03) }

    func finish(_ message: String, success: Bool) {
        title.stringValue = success ? "Eggie 更新完成" : "Eggie 更新未完成"
        stage.stringValue = success ? "新版本已打开" : "请查看下方说明"
        detail.stringValue = message
        spinner.stopAnimation(nil)
        spinner.isHidden = true
        if success { pump(1.5); window.close() }
        else {
            window.setContentSize(NSSize(width: 452, height: 270))
            detail.maximumNumberOfLines = 6
            closeButton.isHidden = false
            bringForward()
            while !closed { pump(0.1) }
        }
    }

    @objc func closeResult() { closed = true; window.close() }
    deinit { if let observer { DistributedNotificationCenter.default().removeObserver(observer) } }
}

final class LaunchGate {
    let fd: Int32
    let app: URL
    init(_ app: URL) throws {
        self.app = app
        fd = open(progressLockURL(app).path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw Failure("无法准备更新提示，当前版本保持运行。") }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_uid == getuid(), info.st_mode & 0o077 == 0,
              flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            Darwin.close(fd)
            throw Failure("另一次更新正在进行，或更新提示记录不可用。")
        }
        try permit("")
    }
    func permit(_ value: String) throws {
        let data = try JSONEncoder().encode(["permit": value])
        guard ftruncate(fd, 0) == 0, lseek(fd, 0, SEEK_SET) == 0 else { throw Failure("无法记录更新状态。") }
        let count = data.withUnsafeBytes { Darwin.write(fd, $0.baseAddress, $0.count) }
        guard count == data.count else { throw Failure("无法记录更新状态。") }
    }
    func release() {
        // Remove only our own lock inode, after all file/recovery operations finish.
        var held = stat(), current = stat()
        let path = progressLockURL(app).path
        if fstat(fd, &held) == 0, lstat(path, &current) == 0,
           held.st_ino == current.st_ino, held.st_dev == current.st_dev { _ = unlink(path) }
        _ = flock(fd, LOCK_UN)
    }
    deinit { Darwin.close(fd) }
}

func guardLaunch(_ app: URL, permit: String) -> Bool {
    let fd = open(progressLockURL(app).path, O_RDONLY | O_NOFOLLOW)
    if fd < 0 {
        if errno == ENOENT { return false }
        if errno == EACCES {
            // Another account's private record can survive a killed helper.
            // The kernel installation lock, held before creating that record,
            // distinguishes a live updater from stale, unreadable metadata.
            let parent = open(app.deletingLastPathComponent().path, O_RDONLY | O_DIRECTORY)
            guard parent >= 0 else { return true }
            defer { Darwin.close(parent) }
            return flock(parent, LOCK_SH | LOCK_NB) != 0
        }
        return true
    }
    defer { Darwin.close(fd) }
    if flock(fd, LOCK_SH | LOCK_NB) == 0 { return false }
    // A torn/unknown record blocks launch; it never grants a launch permit.
    var buffer = [UInt8](repeating: 0, count: 2048)
    let count = Darwin.read(fd, &buffer, buffer.count)
    if count > 0, !permit.isEmpty,
       let values = try? JSONDecoder().decode([String: String].self, from: Data(buffer.prefix(count))),
       values["permit"] == permit { return false }
    DistributedNotificationCenter.default().postNotificationName(
        showNotification, object: app.path, userInfo: nil, deliverImmediately: true)
    pump(0.05)
    return true
}

var progress: ProgressWindow?

func checkSignature(_ app: URL, _ expectedHash: String) throws {
    var code: SecStaticCode?
    let flags = SecCSFlags(rawValue: kSecCSStrictValidate | kSecCSCheckNestedCode | kSecCSCheckAllArchitectures)
    guard SecStaticCodeCreateWithPath(app as CFURL, [], &code) == errSecSuccess, let code,
          SecStaticCodeCheckValidity(code, flags, nil) == errSecSuccess
    else { throw Failure("应用在核对后发生变化，签名验证失败。") }
    var raw: CFDictionary?
    guard SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &raw) == errSecSuccess,
          let info = raw as? [String: Any], let hash = info[kSecCodeInfoUnique as String] as? Data,
          info[kSecCodeInfoIdentifier as String] as? String == "com.huang.eggiedocuflow",
          hash.map({ String(format: "%02x", $0) }).joined() == expectedHash
    else { throw Failure("应用内容与已验证的版本不一致。") }
}

func launch(_ app: URL, arguments: [String] = []) throws -> NSRunningApplication {
    let config = NSWorkspace.OpenConfiguration()
    config.createsNewApplicationInstance = true
    config.arguments = arguments
    var result: Result<NSRunningApplication, Error>?
    NSWorkspace.shared.openApplication(at: app, configuration: config) { application, error in
        if let application { result = .success(application) }
        else { result = .failure(error ?? Failure("新版应用未能打开。")) }
    }
    let end = Date().addingTimeInterval(20)
    while result == nil && Date() < end {
        pump(0.05)
    }
    guard let result else { throw Failure("系统没有确认应用已启动。") }
    return try result.get()
}

func swap(_ installed: URL, _ next: URL) throws {
    guard renameatx_np(AT_FDCWD, installed.path, AT_FDCWD, next.path, UInt32(RENAME_SWAP)) == 0
    else { throw Failure("无法在当前目录安全替换应用，请检查权限和可用空间。") }
}

func waitForReady(_ process: NSRunningApplication, _ marker: URL, _ challenge: String) throws {
    let deadline = Date().addingTimeInterval(60)
    while Date() < deadline && !process.isTerminated {
        if (try? String(contentsOf: marker, encoding: .utf8)) == challenge { return }
        pump(0.1)
    }
    if !process.isTerminated {
        // This is only the candidate process we launched, still waiting at first startup.
        process.terminate()
        let stop = Date().addingTimeInterval(4)
        while !process.isTerminated && Date() < stop {
            pump(0.1)
        }
        if !process.isTerminated { process.forceTerminate() }
    }
    throw Failure("新版未能打开主窗口。")
}

let savedName = "保留版本.app"
let recoveryPrefix = "Eggie 更新恢复-"

func extensionID(_ name: String) -> String? {
    guard let r = name.range(of: #"^\.eggie-update-[a-z0-9_]{8}$"#, options: .regularExpression),
          r == name.startIndex..<name.endIndex else { return nil }
    return String(name.suffix(8))
}

func lockInstallation(_ parent: URL) throws -> Int32 {
    let fd = open(parent.path, O_RDONLY | O_DIRECTORY)
    guard fd >= 0 else { throw Failure("无法打开安装目录。") }
    if flock(fd, LOCK_EX | LOCK_NB) != 0 {
        Darwin.close(fd)
        throw Failure("另一次更新正在进行，请稍后重试。")
    }
    return fd
}

func checkNoOtherInstance(_ app: URL, ignoring ignoredPID: Int32) throws {
    let prefix = app.resolvingSymlinksInPath().path + "/"
    let count = proc_listallpids(nil, 0)
    guard count > 0 else { throw Failure("无法确认其他 Eggie 窗口是否已经退出，请稍后重试。") }
    var pids = [Int32](repeating: 0, count: Int(count) + 1024)
    let found = pids.withUnsafeMutableBytes { proc_listallpids($0.baseAddress, Int32($0.count)) }
    guard found > 0, found < pids.count else { throw Failure("无法完整检查正在运行的程序，请稍后重试。") }
    for pid in pids.prefix(Int(found)) where pid > 0 && pid != getpid() && pid != ignoredPID {
        var buffer = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
        let length = proc_pidpath(pid, &buffer, UInt32(buffer.count))
        // Processes can exit during enumeration. Kernel/system processes may
        // not expose a path, and cannot be an executable in this app bundle.
        if length > 0 {
            let executable = URL(fileURLWithPath: String(cString: buffer)).resolvingSymlinksInPath().path
            if executable.hasPrefix(prefix) {
                throw Failure("同一安装位置还有其他 Eggie 窗口或任务正在运行，请全部退出后再更新。")
            }
        }
    }
}

func waitForOtherInstances(_ app: URL) throws {
    // A second click may briefly start the guarded bootstrap. Give it time to
    // return to the progress window, without terminating any existing work.
    let deadline = Date().addingTimeInterval(3)
    while true {
        do { try checkNoOtherInstance(app, ignoring: 0); return }
        catch { if Date() >= deadline { throw error }; pump(0.1) }
    }
}

struct Receipt: Codable {
    let name: String
    let previousHash: String
    let targetHash: String
}

func prepareRecovery(_ staging: URL, _ visible: URL, _ receipt: Receipt) throws {
    // The receipt and instructions exist before moving any installed bits.
    try files.moveItem(at: staging.appendingPathComponent("Next.app"), to: staging.appendingPathComponent(savedName))
    try JSONEncoder().encode(receipt).write(to: staging.appendingPathComponent("recovery.json"), options: .atomic)
    let script = staging.appendingPathComponent("双击恢复旧版.command")
    let command = """
    #!/bin/sh
    cd -- "$(dirname "$0")" || exit 1
    exec "./保留版本.app/Contents/Frameworks/update-tools/EggieUpdateHelper" --recover
    """
    try command.write(to: script, atomically: true, encoding: .utf8)
    try files.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    let instructions = """
    如果 Eggie 已经正常重新打开，稍等片刻，此临时恢复目录会自动移除。
    如果在更新期间断电或助手中断，请先退出 Eggie，再打开“双击恢复旧版.command”。
    恢复助手会核对两个应用的签名。有文件被改动时会停止并保留两个副本。
    如果助手无法修复原位置，可从此文件夹打开“保留版本.app”继续使用旧版。
    查找原安装位置时，返回本文件夹的上一级，应用名为 \(receipt.name)。
    """
    try instructions.write(to: staging.appendingPathComponent("如何恢复.txt"), atomically: true, encoding: .utf8)
    try files.moveItem(at: staging, to: visible)
}

func cleanRecovery(_ folder: URL) {
    // The visible recovery directory may contain unrelated files after an interruption.
    for name in [savedName, "ready", "recovery.json", "双击恢复旧版.command", "如何恢复.txt"] {
        try? files.removeItem(at: folder.appendingPathComponent(name))
    }
    _ = rmdir(folder.path)
}

func recover(relaunch: Bool) throws {
    guard geteuid() != 0 else { throw Failure("请以原用户运行恢复助手。") }
    let binary = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    let backup = (0..<4).reduce(binary) { current, _ in current.deletingLastPathComponent() }
    let folder = backup.deletingLastPathComponent()
    let parent = folder.deletingLastPathComponent()
    guard backup.lastPathComponent == savedName,
          folder.lastPathComponent.range(of: #"^Eggie 更新恢复-[a-z0-9_]{8}\.noindex$"#, options: .regularExpression) != nil,
          let info = try? files.attributesOfItem(atPath: folder.path),
          (info[.posixPermissions] as? NSNumber)?.intValue == 0o700,
          (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid()
    else { throw Failure("请从原安装目录旁的 Eggie 更新恢复文件夹运行。") }
    let lock = try lockInstallation(parent)
    defer { Darwin.close(lock) }
    let receipt = try JSONDecoder().decode(Receipt.self, from: Data(contentsOf: folder.appendingPathComponent("recovery.json")))
    guard !receipt.name.contains("/"), receipt.name.hasSuffix(".app") else { throw Failure("恢复记录无效。") }
    let current = parent.appendingPathComponent(receipt.name)
    guard current.resolvingSymlinksInPath().path == current.path else { throw Failure("原应用路径已变化。") }
    if (try? checkSignature(current, receipt.previousHash)) != nil {
        if (try? checkSignature(backup, receipt.targetHash)) != nil { cleanRecovery(folder) }
        if relaunch { _ = try launch(current) }
        return
    }
    try checkSignature(backup, receipt.previousHash)
    try checkSignature(current, receipt.targetHash)
    let locations = [current.path, backup.path]
    if NSWorkspace.shared.runningApplications.contains(where: {
        guard let path = $0.bundleURL?.resolvingSymlinksInPath().path else { return false }
        return locations.contains(path) && $0.processIdentifier != getpid()
    }) { throw Failure("请退出这两份 Eggie 后再运行恢复助手。") }
    try swap(current, backup)
    if relaunch { _ = try launch(current) }
    cleanRecovery(folder)
}

func install() throws {
    let args = CommandLine.arguments
    guard args.count == 6, geteuid() != 0, let parentPID = Int32(args[1]), parentPID > 1 else {
        throw Failure("无法确认更新请求。")
    }
    let app = URL(fileURLWithPath: args[2]).standardizedFileURL
    let stage = URL(fileURLWithPath: args[3]).standardizedFileURL
    let parent = app.deletingLastPathComponent()
    guard app.pathExtension == "app", parent == stage.deletingLastPathComponent(),
          let token = extensionID(stage.lastPathComponent),
          stage.resolvingSymlinksInPath().path == stage.path,
          app.resolvingSymlinksInPath().path == app.path else { throw Failure("无法确认安装目录。") }
    let recovery = parent.appendingPathComponent(recoveryPrefix + token + ".noindex")
    let next = recovery.appendingPathComponent(savedName)
    // Hold this across the entire gate lifetime, including the GUI handoff.
    // Other accounts can inspect this lock without reading private gate data.
    let lock: Int32
    do { lock = try lockInstallation(parent) }
    catch { try? files.removeItem(at: stage); throw error }
    defer { Darwin.close(lock) }
    let gate = try LaunchGate(app)
    defer { gate.release() }
    progress = ProgressWindow(app: app)
    guard progress?.window.isVisible == true else { throw Failure("更新提示窗口未能显示，当前版本保持运行。") }
    // The caller keeps its window open until this acknowledgment arrives.
    FileHandle.standardOutput.write(Data("ready\n".utf8))
    let deadline = Date().addingTimeInterval(120)
    while kill(parentPID, 0) == 0 && Date() < deadline { pump(0.1) }
    guard kill(parentPID, 0) != 0 && errno == ESRCH else {
        throw Failure("请先退出正在使用的 Eggie，再重试更新。")
    }
    var cleanup = stage
    var swapped = false
    var mayClean = true
    defer {
        if mayClean {
            if cleanup == recovery { cleanRecovery(recovery) }
            else { try? files.removeItem(at: cleanup) }
        }
    }
    // The initiating GUI is gone; every other process must also have released
    // this bundle. Keep any other user's window and work alive, without swapping.
    try waitForOtherInstances(app)
    do {
        progress?.phase("准备更新 · 核对应用")
        try checkSignature(app, args[4])
        try checkSignature(stage.appendingPathComponent("Next.app"), args[5])
        let receipt = Receipt(name: app.lastPathComponent, previousHash: args[4], targetHash: args[5])
        try prepareRecovery(stage, recovery, receipt)
        cleanup = recovery
        try waitForOtherInstances(app)
        progress?.phase("安装更新")
        try swap(app, next)
        swapped = true
        let challenge = UUID().uuidString
        let permit = "--eggie-update-health=" + token + ":" + challenge
        try gate.permit(permit)
        progress?.phase("正在启动 · 检查新版本")
        let process = try launch(app, arguments: [permit])
        try waitForReady(process, recovery.appendingPathComponent("ready"), challenge)
    } catch {
        if swapped {
            progress?.phase("正在恢复原版本")
            do { try swap(app, next) }
            catch {
                mayClean = false
                throw Failure("更新失败，未能恢复原位置。旧版保留在 " + next.path)
            }
        }
        // Report restoration only after checking the actual original application.
        if (try? checkSignature(app, args[4])) != nil {
            let permit = "--eggie-update-resume=" + UUID().uuidString
            try gate.permit(permit)
            var reopened = false
            if (try? waitForOtherInstances(app)) != nil {
                reopened = (try? launch(app, arguments: [permit])) != nil
            }
            let state = swapped ? "更新未完成，已恢复原版本。" : "更新未开始，原版本未改动。"
            throw Failure(state + (reopened ? "可以继续使用。" : "请重新打开 Eggie。") + "\n" + error.localizedDescription)
        }
        mayClean = false
        throw Failure("更新未完成，暂时无法确认原版本。请保留恢复目录：" + cleanup.path)
    }
}

let checkOnly = CommandLine.arguments.count == 4 && CommandLine.arguments[1] == "--check-running"
let guardOnly = CommandLine.arguments.count == 4 && CommandLine.arguments[1] == "--guard-launch"
if guardOnly {
    exit(guardLaunch(URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL,
                     permit: CommandLine.arguments[3]) ? 75 : 0)
}
let recoveryOnly = CommandLine.arguments.count == 2 && ["--recover", "--recover-no-launch"].contains(CommandLine.arguments[1])
let headless = checkOnly || (recoveryOnly && CommandLine.arguments[1] == "--recover-no-launch")
do {
    if checkOnly {
        guard let ignoredPID = Int32(CommandLine.arguments[3]), ignoredPID > 1 else { throw Failure("无法确认更新窗口。") }
        try checkNoOtherInstance(URL(fileURLWithPath: CommandLine.arguments[2]), ignoring: ignoredPID)
    } else if recoveryOnly { try recover(relaunch: !headless) } else {
        try install()
        progress?.finish("更新已完成，可以继续使用。", success: true)
    }
}
catch {
    if headless { FileHandle.standardError.write(Data(error.localizedDescription.utf8)); exit(1) }
    if let progress {
        progress.finish(error.localizedDescription, success: false)
        exit(1)
    }
    // An error after the old window has exited must still reach the user.
    let application = NSApplication.shared
    application.setActivationPolicy(.accessory)
    let alert = NSAlert()
    alert.messageText = "Eggie 更新未完成"
    alert.informativeText = error.localizedDescription
    alert.addButton(withTitle: "关闭")
    application.activate(ignoringOtherApps: true)
    alert.runModal()
    exit(1)
}
