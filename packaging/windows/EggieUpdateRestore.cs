// Standalone recovery: system .NET only, no Eggie DLLs or PowerShell scripts.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

internal static class EggieUpdateRestore {
    const string RegistryKey = @"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{7DA942BC-98E2-48DB-93C7-741D7FD9C1C3}_is1";
    static readonly HashSet<string> Trusted = new HashSet<string> {
        "S-1-5-18", "S-1-5-32-544",
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    };
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 8 * 1024 * 1024 };
    static string Field(Dictionary<string, object> item, string name) { return (string)item[name]; }
    static bool Equal(string a, string b) { return String.Equals(a, b, StringComparison.OrdinalIgnoreCase); }
    static void Require(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
    static string Digest(string path) {
        using (var input = File.OpenRead(path)) using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
    }
    static void NoLinks(string path) {
        for (string current = Path.GetFullPath(path); !String.IsNullOrEmpty(current); current = Path.GetDirectoryName(current)) {
            if (File.Exists(current) || Directory.Exists(current))
                Require((File.GetAttributes(current) & FileAttributes.ReparsePoint) == 0, "A recovery path contains a link.");
        }
    }
    static void Protected(string path) {
        NoLinks(path);
        FileSystemSecurity acl = Directory.Exists(path) ? (FileSystemSecurity)Directory.GetAccessControl(path) : File.GetAccessControl(path);
        Require(Trusted.Contains(acl.GetOwner(typeof(SecurityIdentifier)).Value), "Recovery files must be owned by the system or administrators.");
        foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier))) {
            if ((rule.PropagationFlags & PropagationFlags.InheritOnly) != 0 || rule.AccessControlType != AccessControlType.Allow) continue;
            // Same write/delete/ownership mask as the updater's installation check.
            if (((long)rule.FileSystemRights & 0x500D0156L) != 0)
                Require(Trusted.Contains(rule.IdentityReference.Value), "An ordinary account can modify a recovery file.");
        }
    }
    static Dictionary<string, object> ReadRecord(string path) {
        Protected(path);
        Require(new FileInfo(path).Length <= 8 * 1024 * 1024, "Recovery record is too large.");
        return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8));
    }
    static void CheckTree(string root, string version, string build, string snapshotPath) {
        Protected(root);
        var stamp = ReadRecord(Path.Combine(root, "eggie-runtime.json"));
        Require(Convert.ToInt32(stamp["schema"]) == 1 && Field(stamp, "version") == version && Field(stamp, "build") == build,
                "The backup does not match the original version.");
        // New transactions record the actual backup, including any drift that
        // triggered full repair. Old transactions still require a pristine stamp.
        bool hasSnapshot = File.Exists(snapshotPath);
        var record = hasSnapshot ? ReadRecord(snapshotPath) : stamp;
        Require(Convert.ToInt32(record["schema"]) == 1 && Field(record, "version") == version && Field(record, "build") == build,
                "The backup snapshot does not match the original version.");
        var files = (Dictionary<string, object>)record["files"];
        Require(files.ContainsKey("Eggie DocuFlow.exe"), "Original program record is missing.");
        Require(!hasSnapshot || files.ContainsKey("eggie-runtime.json"), "Original installation record is missing.");
        CheckNoLinks(root);
        var expectedPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in files) {
            Require(!String.IsNullOrEmpty(entry.Key) && !entry.Key.Contains(":") && !entry.Key.Contains("\\") &&
                    !Path.IsPathRooted(entry.Key) && !entry.Key.StartsWith("/"), "Invalid backup filename.");
            foreach (var part in entry.Key.Split('/'))
                Require(part != "" && part != "." && part != ".." && !part.EndsWith(".") && !part.EndsWith(" "), "Invalid backup path.");
            string path = Path.GetFullPath(Path.Combine(root, entry.Key));
            Require(path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase), "A backup path escapes its directory.");
            Require(expectedPaths.Add(path), "Duplicate backup filename.");
            Protected(path);
            string expected = (string)entry.Value;
            Require(Regex.IsMatch(expected, "^[a-f0-9]{64}$") && Digest(path) == expected, "An original backup file differs from its record.");
        }
        if (hasSnapshot) {
            foreach (string path in Directory.GetFiles(root, "*", SearchOption.AllDirectories))
                Require(expectedPaths.Contains(path), "An unexpected file was added to the backup.");
        }
    }
    static void CheckNoLinks(string root) {
        foreach (string entry in Directory.GetFileSystemEntries(root)) {
            Protected(entry);
            if (Directory.Exists(entry)) CheckNoLinks(entry);
        }
    }
    static void CheckNoApp(string exe) {
        foreach (var process in Process.GetProcessesByName("Eggie DocuFlow")) using (process) {
            if (process.HasExited) continue;
            Require(!Equal(process.MainModule.FileName, exe), "Close the Eggie window before restoring it.");
        }
    }
    static void CheckRegistryBackup(string path) {
        Protected(path);
        Require(new FileInfo(path).Length < 4 * 1024 * 1024, "Registry backup is too large.");
        string expected = RegistryKey.Replace("HKLM\\", "HKEY_LOCAL_MACHINE\\");
        string content = File.ReadAllText(path, Encoding.Unicode);
        Require(content.StartsWith("Windows Registry Editor Version 5.00"), "Invalid registry backup.");
        int headers = 0;
        foreach (Match match in Regex.Matches(content, @"^\[([^\]]+)\]", RegexOptions.Multiline)) {
            string name = match.Groups[1].Value;
            Require(Equal(name, expected) || name.StartsWith(expected + "\\", StringComparison.OrdinalIgnoreCase),
                    "Registry backup includes another application.");
            headers++;
        }
        Require(headers > 0, "Registry backup has no installation record.");
    }
    static void PublishRecovered(string job) {
        // Publish only after both files and the registry have been restored.
        // An atomic replacement also updates a monitor already showing failure.
        string result = Path.Combine(job, "result");
        if (File.Exists(result)) Protected(result);
        string pending = Path.Combine(job, "result-" + Guid.NewGuid().ToString("N") + ".tmp");
        try {
            using (var stream = new FileStream(pending, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                byte[] bytes = Encoding.UTF8.GetBytes("recovered");
                stream.Write(bytes, 0, bytes.Length);
                stream.Flush(true);
            }
            for (int attempt = 0; ; attempt++) {
                try {
                    if (File.Exists(result)) File.Replace(pending, result, null);
                    else File.Move(pending, result);
                    break;
                } catch (IOException) {
                    // The monitor may briefly have the previous result open.
                    if (attempt >= 20) throw;
                    System.Threading.Thread.Sleep(50);
                }
            }
        } finally { if (File.Exists(pending)) File.Delete(pending); }
    }
    static int Main(string[] args) {
        Console.OutputEncoding = Encoding.UTF8;
        string job = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        try {
            Require(args.Length == 0, "This tool accepts no destination or command arguments.");
            var principal = new WindowsPrincipal(WindowsIdentity.GetCurrent());
            Require(principal.IsInRole(WindowsBuiltInRole.Administrator), "Run this recovery tool as administrator.");
            string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            Require(Equal(Path.GetDirectoryName(job), programFiles) && Regex.IsMatch(Path.GetFileName(job), @"^\.eggie-update-[a-f0-9]{32}$"),
                    "This is not a protected Eggie recovery folder.");
            Protected(programFiles); Protected(job);
            Require(File.Exists(Path.Combine(job, "installing")), "This update is not marked as interrupted.");
            Protected(Path.Combine(job, "installing"));
            var config = ReadRecord(Path.Combine(job, "rollback.json"));
            Require(Equal(Field(config, "registry_key"), RegistryKey), "This backup belongs to another product.");
            string app = Path.GetFullPath(Field(config, "install_dir")).TrimEnd(Path.DirectorySeparatorChar);
            Require(Equal(Path.GetDirectoryName(app), programFiles) && !Path.GetFileName(app).StartsWith("."), "Unexpected original installation path.");
            NoLinks(app);
            string backup = Path.Combine(job, "backup");
            string candidate = Directory.Exists(backup) ? backup : app;
            string version = Field(config, "version"), build = Field(config, "build");
            Require(Regex.IsMatch(version, @"^[0-9]+\.[0-9]+\.[0-9]+$") && Regex.IsMatch(build, "^[0-9]{10}$"), "Invalid original version.");
            using (var updateLock = new FileStream(Path.Combine(programFiles, ".eggie-docuflow-update.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None)) {
                CheckTree(candidate, version, build, Path.Combine(job, "backup-tree.json"));
                if (Directory.Exists(app)) CheckNoLinks(app);
                CheckNoApp(Path.Combine(app, "Eggie DocuFlow.exe"));
                string savedRegistry = Path.Combine(job, "uninstall.reg");
                CheckRegistryBackup(savedRegistry);
                Console.WriteLine("将恢复 Eggie " + version + "（" + build + "）");
                Console.WriteLine("原安装位置：" + app);
                Console.WriteLine("输入 RESTORE 并按回车确认；其他输入取消。");
                if (Console.ReadLine() != "RESTORE") return 0;
                if (Directory.Exists(backup)) {
                    if (Directory.Exists(app)) Directory.Move(app, Path.Combine(job, "interrupted-" + Guid.NewGuid().ToString("N")));
                    Directory.Move(backup, app);
                }
                var start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "reg.exe"), "import \"" + savedRegistry + "\" /reg:64");
                start.UseShellExecute = false;
                using (var process = Process.Start(start)) {
                    Require(process.WaitForExit(30000) && process.ExitCode == 0, "Could not restore the installation record; keep the recovery folder.");
                }
                PublishRecovered(job);
                File.Delete(Path.Combine(job, "installing"));
                Console.WriteLine("Recovery complete. 请通过平时的快捷方式打开 Eggie。");
            }
            return 0;
        } catch (Exception error) {
            Console.Error.WriteLine("恢复尚未完成，已保留现有文件和备份。" + error.Message);
            return 2;
        }
    }
}
