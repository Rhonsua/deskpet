// Decode bounded LZMS buffers with the Windows 8+ Compression API. The inner
// ZIP is still read by .NET, so Setup keeps its per-file path and manifest rules.
using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

static class InstallerPayload {
    const int BlockSize = 32 * 1024 * 1024;
    const int MaxPacked = BlockSize + 65536;
    const ulong MaxTotal = 8UL * 1024 * 1024 * 1024;
    [DllImport("cabinet.dll", SetLastError = true)]
    static extern bool CreateDecompressor(uint algorithm, IntPtr allocation, out IntPtr handle);
    [DllImport("cabinet.dll", SetLastError = true)]
    static extern bool Decompress(IntPtr handle, byte[] input, UIntPtr inputLength,
                                  [Out] byte[] output, UIntPtr outputLength, out UIntPtr written);
    [DllImport("cabinet.dll", SetLastError = true)]
    static extern bool CloseDecompressor(IntPtr handle);

    public static ZipArchive Open(string directory, Action<int> progress, out int preparationProgress) {
        string packed = Path.Combine(directory, "payload.tlz");
        if (!File.Exists(packed)) {
            preparationProgress = 0;
            string legacy = Path.Combine(directory, "payload.zip");
            if (!File.Exists(legacy)) throw new IOException("缺少安装数据，请重新下载安装包。");
            return ZipFile.OpenRead(legacy);
        }
        preparationProgress = 15;
        // DeleteOnClose removes the decoded ZIP on success, failure and process
        // exit. It never lives in the user's installed program or data folder.
        string temporary = Path.Combine(Path.GetTempPath(), "TianyiPayload-" + Guid.NewGuid().ToString("N") + ".zip");
        FileStream decoded = new FileStream(temporary, FileMode.CreateNew, FileAccess.ReadWrite,
                                            FileShare.None, 65536, FileOptions.DeleteOnClose);
        try {
            Decode(packed, decoded, progress);
            decoded.Position = 0;
            return new ZipArchive(decoded, ZipArchiveMode.Read);
        } catch {
            decoded.Dispose();
            throw;
        }
    }

    static void Decode(string path, Stream output, Action<int> progress) {
        using (var reader = new BinaryReader(File.OpenRead(path)))
        using (var checksum = SHA256.Create()) {
            if (!reader.ReadBytes(8).SequenceEqual(Encoding.ASCII.GetBytes("TYPLZMS1")))
                throw new IOException("安装包格式不正确，请重新下载。");
            ulong total = reader.ReadUInt64();
            byte[] expected = reader.ReadBytes(32);
            if (total == 0 || total > MaxTotal || expected.Length != 32)
                throw new IOException("安装包大小信息不正确，请重新下载。");
            IntPtr handle;
            if (!CreateDecompressor(5, IntPtr.Zero, out handle))
                throw new IOException("无法启动系统解压功能，请重启电脑后重试。");
            try {
                byte[] buffer = new byte[BlockSize];
                ulong copied = 0;
                while (copied < total) {
                    uint original = reader.ReadUInt32(), packed = reader.ReadUInt32();
                    if (original == 0 || original > BlockSize || original > total - copied ||
                        packed == 0 || packed > MaxPacked)
                        throw new IOException("安装数据块大小异常，请重新下载。");
                    byte[] data = reader.ReadBytes((int)packed);
                    if (data.Length != packed) throw new IOException("安装包未下载完整。");
                    UIntPtr written;
                    if (!Decompress(handle, data, (UIntPtr)packed, buffer, (UIntPtr)original, out written) ||
                        written.ToUInt64() != original)
                        throw new IOException("安装数据解压失败，请重新下载安装包。");
                    checksum.TransformBlock(buffer, 0, (int)original, null, 0);
                    output.Write(buffer, 0, (int)original);
                    copied += original;
                    progress((int)(copied * 15 / total));
                }
                checksum.TransformFinalBlock(new byte[0], 0, 0);
                if (reader.BaseStream.Position != reader.BaseStream.Length || !checksum.Hash.SequenceEqual(expected))
                    throw new IOException("安装包完整性校验失败，请重新下载。");
            } finally {
                CloseDecompressor(handle);
            }
        }
    }
}
