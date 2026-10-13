// Fixed, parent-owned diagnostic only. Compile with /noconfig and System.dll.
using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;

internal static class AppContainerAccess
{
    private const uint GenericRead = 0x80000000;
    private const uint ShareRead = 1;
    private const uint OpenExisting = 3;
    private static readonly IntPtr InvalidHandle = new IntPtr(-1);
    private static readonly byte[] Allowed = Encoding.ASCII.GetBytes("xuxia-allowed-fixture-v1\r\n");
    private static readonly byte[] Denied = Encoding.ASCII.GetBytes("xuxia-denied-fixture-v1\r\n");
    private static readonly byte[] Nonce = Encoding.ASCII.GetBytes("xuxia-loopback-control-v1\n");

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    private static extern IntPtr CreateFileW(string name, uint access, uint share,
        IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ReadFile(IntPtr handle, byte[] buffer, uint count,
        out uint read, IntPtr overlapped);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    private sealed class FileFact
    {
        internal bool Attempted = true, Opened, ReadAttempted, ContentOk, CloseOk = true;
        internal int? OpenError, ReadError;
        internal string Json()
        {
            return "{\"attempted\":" + B(Attempted) + ",\"opened\":" + B(Opened)
                + ",\"open_error\":" + N(OpenError) + ",\"read_attempted\":" + B(ReadAttempted)
                + ",\"read_error\":" + N(ReadError) + ",\"content_ok\":" + B(ContentOk)
                + ",\"close_ok\":" + B(CloseOk) + "}";
        }
    }

    private sealed class SocketFact
    {
        internal bool Attempted, SocketCreated, TimedOut, CloseOk = true;
        internal int? SocketError, ConnectError, PollError, SendError;
        internal int SentBytes;
        internal string Json()
        {
            return "{\"attempted\":" + B(Attempted) + ",\"socket_created\":" + B(SocketCreated)
                + ",\"socket_error\":" + N(SocketError) + ",\"connect_error\":" + N(ConnectError)
                + ",\"poll_error\":" + N(PollError) + ",\"timed_out\":" + B(TimedOut)
                + ",\"send_error\":" + N(SendError) + ",\"sent_bytes\":" + SentBytes.ToString(CultureInfo.InvariantCulture)
                + ",\"close_ok\":" + B(CloseOk) + "}";
        }
    }

    private static string B(bool value) { return value ? "true" : "false"; }
    private static string N(int? value) { return value.HasValue ? value.Value.ToString(CultureInfo.InvariantCulture) : "null"; }

    private static bool ValidPath(string path, string leaf)
    {
        if (String.IsNullOrEmpty(path) || path.Length > 240 || path.IndexOf('\0') >= 0
            || path.IndexOf('/') >= 0 || path.Length < 4 || !((path[0] >= 'A' && path[0] <= 'Z') || (path[0] >= 'a' && path[0] <= 'z'))
            || path[1] != ':' || path[2] != '\\' || path.StartsWith("\\\\", StringComparison.Ordinal)
            || !String.Equals(Path.GetFileName(path), leaf, StringComparison.Ordinal)) return false;
        string[] parts = path.Substring(3).Split('\\');
        foreach (string part in parts)
        {
            if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(" ", StringComparison.Ordinal)
                || part.EndsWith(".", StringComparison.Ordinal)) return false;
            string stem = part.Split('.')[0].ToUpperInvariant();
            if (stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL"
                || (stem.Length == 4 && (stem.StartsWith("COM", StringComparison.Ordinal)
                    || stem.StartsWith("LPT", StringComparison.Ordinal)) && stem[3] >= '1' && stem[3] <= '9')) return false;
            foreach (char c in part)
                if (c < 32 || c == ':' || c == '<' || c == '>' || c == '"' || c == '|'
                    || c == '?' || c == '*') return false;
        }
        return true;
    }

    private static bool ValidArgs(string[] args, out int port)
    {
        port = 0;
        try
        {
            if (args == null || args.Length != 4 || (args[0] != "ordinary" && args[0] != "contained")
                || !ValidPath(args[1], "allowed.txt") || !ValidPath(args[2], "denied.txt")
                || !String.Equals(Path.GetDirectoryName(args[1]), Path.GetDirectoryName(args[2]), StringComparison.OrdinalIgnoreCase)
                || !Int32.TryParse(args[3], NumberStyles.None, CultureInfo.InvariantCulture, out port)
                || port < 1 || port > 65535
                || args[3] != port.ToString(CultureInfo.InvariantCulture)) return false;
            return true;
        }
        catch { return false; } // Input-only path parsing must never become an exit-1 probe failure.
    }

    private static FileFact MeasureFile(string path, byte[] expected)
    {
        FileFact fact = new FileFact();
        IntPtr handle = CreateFileW(path, GenericRead, ShareRead, IntPtr.Zero, OpenExisting, 0, IntPtr.Zero);
        if (handle == InvalidHandle) { fact.OpenError = Marshal.GetLastWin32Error(); return fact; }
        fact.Opened = true;
        try
        {
            byte[] bytes = new byte[expected.Length + 1];
            uint count;
            fact.ReadAttempted = true;
            bool ok = ReadFile(handle, bytes, (uint)bytes.Length, out count, IntPtr.Zero);
            if (!ok) fact.ReadError = Marshal.GetLastWin32Error();
            else if (count == expected.Length)
            {
                fact.ContentOk = true;
                for (int i = 0; i < expected.Length; i++)
                    if (bytes[i] != expected[i]) { fact.ContentOk = false; break; }
            }
        }
        finally { fact.CloseOk = CloseHandle(handle); }
        return fact;
    }

    private static SocketFact MeasureSocket(IPAddress address, int port, bool sendNonce)
    {
        SocketFact fact = new SocketFact();
        fact.Attempted = true;
        Socket socket = null;
        try
        {
            try { socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp); fact.SocketCreated = true; }
            catch (SocketException e) { fact.SocketError = e.NativeErrorCode; return fact; }
            socket.Blocking = false;
            try { socket.Connect(new IPEndPoint(address, port)); fact.ConnectError = 0; }
            catch (SocketException e)
            {
                if (e.NativeErrorCode != 10035) fact.ConnectError = e.NativeErrorCode;
                else
                {
                    try
                    {
                        if (!socket.Poll(1000000, SelectMode.SelectWrite)
                            && !socket.Poll(0, SelectMode.SelectError)) fact.TimedOut = true;
                        else fact.ConnectError = (int)socket.GetSocketOption(SocketOptionLevel.Socket, SocketOptionName.Error);
                    }
                    catch (SocketException poll) { fact.PollError = poll.NativeErrorCode; }
                }
            }
            if (sendNonce && fact.ConnectError == 0 && !fact.TimedOut && !fact.PollError.HasValue)
            {
                Stopwatch timer = Stopwatch.StartNew();
                for (int attempts = 0; fact.SentBytes < Nonce.Length && attempts < 32
                     && timer.ElapsedTicks < Stopwatch.Frequency; attempts++)
                {
                    long remainingMicros = (Stopwatch.Frequency - timer.ElapsedTicks) * 1000000L / Stopwatch.Frequency;
                    if (remainingMicros <= 0) break;
                    int waitMicros = (int)Math.Min(100000L, remainingMicros);
                    try { if (!socket.Poll(waitMicros, SelectMode.SelectWrite)) continue; }
                    catch (SocketException e) { fact.PollError = e.NativeErrorCode; break; }
                    try
                    {
                        int sent = socket.Send(Nonce, fact.SentBytes, Nonce.Length - fact.SentBytes, SocketFlags.None);
                        if (sent == 0) break; // No native error was observed; preserve partial-byte fact.
                        fact.SentBytes += sent;
                    }
                    catch (SocketException e) { fact.SendError = e.NativeErrorCode; break; }
                }
                if (fact.SentBytes == Nonce.Length) fact.SendError = 0;
            }
        }
        finally
        {
            if (socket != null)
                try { socket.Close(); } catch { fact.CloseOk = false; }
        }
        return fact;
    }

    private static int Main(string[] args)
    {
        int port;
        try
        {
            if (!ValidArgs(args, out port)) return 2;
            string mode = args[0];
            FileFact allowed = MeasureFile(args[1], Allowed);
            FileFact denied = MeasureFile(args[2], Denied);
            SocketFact loopback = MeasureSocket(IPAddress.Loopback, port, mode == "ordinary");
            SocketFact external = mode == "contained"
                ? MeasureSocket(new IPAddress(new byte[] { 192, 0, 2, 1 }), 443, false)
                : new SocketFact();
            if (!allowed.CloseOk || !denied.CloseOk || !loopback.CloseOk || !external.CloseOk) return 1;
            string line = "{\"protocol\":\"xuxia-appcontainer-access\",\"version\":1,\"mode\":\"" + mode
                + "\",\"file_allowed\":" + allowed.Json() + ",\"file_denied\":" + denied.Json()
                + ",\"loopback\":" + loopback.Json() + ",\"external\":" + external.Json() + "}\r\n";
            byte[] output = Encoding.ASCII.GetBytes(line);
            if (output.Length > 4096) return 1;
            Stream stdout = Console.OpenStandardOutput();
            stdout.Write(output, 0, output.Length);
            stdout.Flush();
            return 0;
        }
        catch { return 1; }
    }
}
