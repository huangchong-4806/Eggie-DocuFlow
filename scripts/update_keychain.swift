// Release-only signing helper. Never packaged into Eggie, never exports a private key.
import Foundation
import Security
import CryptoKit
import LocalAuthentication

enum SigningError: Error {
    case usage, keychain(OSStatus), invalidKey, publicKeyMismatch, invalidPayload
}

let identity: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "com.huang.eggiedocuflow.update-signing",
    kSecAttrAccount as String: "ed25519-release-v1"
]

func readKey(create: Bool) throws -> Curve25519.Signing.PrivateKey {
    var query = identity
    query[kSecReturnData as String] = true
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    let context = LAContext()
    context.interactionNotAllowed = true
    query[kSecUseAuthenticationContext as String] = context
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    if status == errSecSuccess {
        guard let data = item as? Data, data.count == 32 else { throw SigningError.invalidKey }
        return try Curve25519.Signing.PrivateKey(rawRepresentation: data)
    }
    guard status == errSecItemNotFound, create else { throw SigningError.keychain(status) }
    let key = Curve25519.Signing.PrivateKey()
    // Do not mutate rawRepresentation: CryptoKit may share that buffer with key.
    // CryptoKit owns the key's lifetime; private bytes never leave this process/Keychain.
    let data = key.rawRepresentation
    var attributes = identity
    attributes[kSecAttrLabel as String] = "Eggie DocuFlow 正式更新签名"
    attributes[kSecAttrDescription as String] = "Ed25519 release signing seed. Do not delete or replace while existing clients trust this key."
    attributes[kSecAttrSynchronizable as String] = false
    attributes[kSecValueData as String] = data
    let result = SecItemAdd(attributes as CFDictionary, nil)
    guard result == errSecSuccess else { throw SigningError.keychain(result) }
    return try readKey(create: false)
}

do {
    let args = CommandLine.arguments
    guard args.count >= 2 else { throw SigningError.usage }
    if args[1] == "self-test", args.count == 2 {
        let key = Curve25519.Signing.PrivateKey()
        let data = Data("Eggie signing helper self-test".utf8)
        let signature = try key.signature(for: data)
        let restored = try Curve25519.Signing.PrivateKey(rawRepresentation: key.rawRepresentation)
        guard key.publicKey.isValidSignature(signature, for: data),
              restored.publicKey.rawRepresentation == key.publicKey.rawRepresentation,
              !key.publicKey.isValidSignature(signature, for: Data("changed".utf8)) else {
            throw SigningError.invalidKey
        }
        print("Signing self-test passed; no Keychain item accessed.")
    } else if args[1] == "init", args.count == 3 {
        let key = try readKey(create: true)
        let publicData = key.publicKey.rawRepresentation
        let output = URL(fileURLWithPath: args[2])
        let encoded = Data((publicData.base64EncodedString() + "\n").utf8)
        if FileManager.default.fileExists(atPath: output.path) {
            guard try Data(contentsOf: output) == encoded else { throw SigningError.publicKeyMismatch }
        } else {
            try encoded.write(to: output, options: .withoutOverwriting)
        }
        let fingerprint = SHA256.hash(data: publicData).map { String(format: "%02x", $0) }.joined()
        print("Keychain key ready. Public-key SHA256: \(fingerprint)")
    } else if args[1] == "public", args.count == 2 {
        print(try readKey(create: false).publicKey.rawRepresentation.base64EncodedString())
    } else if args[1] == "sign", args.count == 2 {
        let data = FileHandle.standardInput.readData(ofLength: 256 * 1024 + 1)
        guard !data.isEmpty, data.count <= 256 * 1024 else { throw SigningError.invalidPayload }
        let signature = try readKey(create: false).signature(for: data)
        print(signature.base64EncodedString())
    } else {
        throw SigningError.usage
    }
} catch SigningError.keychain(let status) {
    fputs("Keychain unavailable (OSStatus \(status)); no key was exported or replaced.\n", stderr)
    exit(2)
} catch {
    fputs("Signing helper refused the operation. Use init <public-key-path>, public, sign, or self-test.\n", stderr)
    exit(2)
}
