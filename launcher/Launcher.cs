using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Windows.Forms;

static class Launcher {
    const string Url = "http://127.0.0.1:8765/";
    static bool Ready() {
        try {
            var request = (HttpWebRequest)WebRequest.Create(Url + "api/status");
            request.Proxy = null; request.Timeout = 1000;
            using (var response = request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream())) {
                string status = reader.ReadToEnd();
                return status.Contains("\"token\"") && status.Contains("\"platform\"") && status.Contains("\"providers\"");
            }
        } catch { return false; }
    }
    static bool PortOccupied() {
        try { using (var client = new TcpClient()) { client.Connect("127.0.0.1", 8765); return true; } }
        catch { return false; }
    }
    [STAThread]
    static int Main(string[] args) {
        bool quiet = Array.IndexOf(args, "--check") >= 0 || Array.IndexOf(args, "--no-browser") >= 0;
        if (Array.IndexOf(args, "--check") >= 0) return Ready() ? 0 : 1;
        bool created;
        using (var mutex = new Mutex(true, "Local\\DreadOSLauncher", out created)) {
            if (!created) return 0;
            try {
                string root = AppDomain.CurrentDomain.BaseDirectory;
                if (!Ready()) {
                    if (PortOccupied()) throw new Exception("Port 8765 is occupied by an unresponsive or different service. Close that service, then try again.");
                    string python = Path.Combine(root, ".venv-voice", "Scripts", "python.exe");
                    string boot = Path.Combine(root, "launcher", "server_boot.py");
                    if (!File.Exists(python) || !File.Exists(boot)) throw new Exception("Keep DreadOS.exe in your DreadOS project folder. Its Python environment and launcher files are required.");
                    var start = new ProcessStartInfo(python, "\"" + boot + "\"");
                    start.WorkingDirectory = root; start.UseShellExecute = false; start.CreateNoWindow = true;
                    start.EnvironmentVariables["JARVIS_PORT"] = "8765";
                    using (var process = Process.Start(start)) {
                        bool ready = false;
                        for (int i = 0; i < 90; i++) {
                            if (Ready()) { ready = true; break; }
                            if (process.HasExited) break;
                            Thread.Sleep(500);
                        }
                        if (!ready) throw new Exception("DreadOS did not become ready. Details are in data\\launcher-server.log. If startup is still running, wait a moment and try again.");
                    }
                }
                if (!quiet) Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
                return 0;
            } catch (Exception error) {
                if (!quiet) MessageBox.Show(error.Message, "DreadOS could not start", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }
}
