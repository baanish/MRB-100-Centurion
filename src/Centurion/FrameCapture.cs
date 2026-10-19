using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Configuration;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// Records playtest video inside the game while Capture.Enabled is on: the game's own frame, HUD included, as the
/// framework's screenshot step takes it (ScreenCapture, so a minimized window or a locked PC still records, and the
/// desktop never is). Each frame goes CaptureScreenshotIntoRenderTexture, AsyncGPUReadback, then a JPG encode and write
/// on the thread pool, so the main thread never waits on the GPU or the disk; a frame is dropped, never queued, once
/// <see cref="MaxInFlight"/> are on their way. Every enable writes a new folder of numbered JPGs and, when it ends,
/// frames.json (<see cref="FrameIndex"/>), which tools/Make-Video.ps1 turns into an MP4. Off, it does no per-frame work.
/// </summary>
public sealed class FrameCapture : MonoBehaviour
{
    /// <summary>Six frames is 300 ms behind at 20 fps; a deeper queue would only hold memory the sim needs.</summary>
    const int MaxInFlight = 6;

    const int JpgQuality = 85;

    /// <summary>How long a stop waits for frames on their way before it writes frames.json without them.</summary>
    const float DrainTimeoutS = 5f;

    sealed class Session
    {
        public string Dir = "";
        public float StartReal;
        public float NextAt;
        public int NextIndex;
        public int InFlight;
        public int Dropped;
        public int Failed;
        public int Width;
        public int Height;
        public readonly ConcurrentBag<FrameIndex.Entry> Frames = new();
    }

    CenturionLog log = null!;
    ConfigEntry<bool> enabledEntry = null!;
    ConfigEntry<int> fps = null!;
    ConfigEntry<float> maxSeconds = null!;
    ConfigEntry<string> folder = null!;
    Session? session;
    RenderTexture? target;

    /// <summary>
    /// CaptureScreenshotIntoRenderTexture copies the back buffer as it lies in memory, upside down where the graphics API
    /// puts row 0 at the top (Direct3D 11, which the game runs on), so those rows are flipped back before encoding.
    /// </summary>
    bool flipRows;

    readonly ConcurrentBag<byte[]> buffers = new();

    public void Bind(CenturionLog log, ConfigEntry<bool> enabled, ConfigEntry<int> fps, ConfigEntry<float> maxSeconds, ConfigEntry<string> folder)
    {
        this.log = log;
        enabledEntry = enabled;
        this.fps = fps;
        this.maxSeconds = maxSeconds;
        this.folder = folder;
        flipRows = SystemInfo.graphicsUVStartsAtTop;
        enabled.SettingChanged += (_, _) => Apply();
        Apply();
    }

    void Apply()
    {
        if (enabledEntry.Value && session == null)
        {
            Begin();
        }
        else if (!enabledEntry.Value && session != null)
        {
            StartCoroutine(End(session));
            session = null;
        }
    }

    void Begin()
    {
        string root = string.IsNullOrEmpty(folder.Value) ? Path.Combine(Paths.BepInExRootPath, "captures") : folder.Value;
        string dir = Path.Combine(root, DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture));
        for (int n = 2; Directory.Exists(dir); n++)
        {
            dir = Path.Combine(root, DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + "-" + n);
        }

        try
        {
            Directory.CreateDirectory(dir);
        }
        catch (Exception e)
        {
            log.Error($"capture not started, {dir} could not be made: {e.Message}");
            enabledEntry.Value = false;
            return;
        }

        float now = Time.realtimeSinceStartup;
        session = new Session { Dir = dir, StartReal = now, NextAt = now };
        log.Info($"capture started: {dir}");
        StartCoroutine(Record(session));
    }

    IEnumerator Record(Session s)
    {
        var endOfFrame = new WaitForEndOfFrame();
        float interval = 1f / Mathf.Max(1, fps.Value);
        while (session == s)
        {
            yield return endOfFrame;
            if (session != s)
            {
                yield break;
            }

            float now = Time.realtimeSinceStartup;
            if (now - s.StartReal >= maxSeconds.Value)
            {
                log.Info(Invariant($"capture reached Capture.MaxSeconds = {maxSeconds.Value}"));
                enabledEntry.Value = false;
                yield break;
            }

            if (FrameIndex.Due(now, ref s.NextAt, interval))
            {
                Request(s, now);
            }
        }
    }

    void Request(Session s, float now)
    {
        int width = Screen.width;
        int height = Screen.height;
        if (width <= 0 || height <= 0 || Volatile.Read(ref s.InFlight) >= MaxInFlight)
        {
            s.Dropped++;
            return;
        }

        if (target == null || target.width != width || target.height != height)
        {
            if (target != null)
            {
                target.Release();
                Destroy(target);
            }

            target = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32);
            target.Create();
        }

        if (s.Width == 0)
        {
            s.Width = width;
            s.Height = height;
        }

        var entry = new FrameIndex.Entry(s.NextIndex++, Time.time, now, Time.frameCount);
        Interlocked.Increment(ref s.InFlight);
        ScreenCapture.CaptureScreenshotIntoRenderTexture(target);
        // The readback copies the texture in command order, so the next capture may reuse it straight away.
        AsyncGPUReadback.Request(target, 0, TextureFormat.RGBA32, request => OnReadback(s, entry, width, height, request));
    }

    void OnReadback(Session s, FrameIndex.Entry entry, int width, int height, AsyncGPUReadbackRequest request)
    {
        if (request.hasError)
        {
            Interlocked.Increment(ref s.Failed);
            Interlocked.Decrement(ref s.InFlight);
            return;
        }

        int length = width * height * 4;
        byte[] pixels = RentBuffer(length);
        request.GetData<byte>().CopyTo(pixels);
        bool flip = flipRows;
        ThreadPool.QueueUserWorkItem(_ => Encode(s, entry, pixels, width, height, flip));
    }

    void Encode(Session s, FrameIndex.Entry entry, byte[] pixels, int width, int height, bool flip)
    {
        try
        {
            if (flip)
            {
                FlipRows(pixels, width * 4, height);
            }

            byte[] jpg = ImageConversion.EncodeArrayToJPG(pixels, GraphicsFormat.R8G8B8A8_UNorm, (uint)width, (uint)height, 0, JpgQuality);
            File.WriteAllBytes(Path.Combine(s.Dir, FrameIndex.FileName(entry.Index)), jpg);
            s.Frames.Add(entry);
        }
        catch (Exception)
        {
            Interlocked.Increment(ref s.Failed);
        }
        finally
        {
            buffers.Add(pixels);
            Interlocked.Decrement(ref s.InFlight);
        }
    }

    byte[] RentBuffer(int length)
    {
        while (buffers.TryTake(out byte[] buffer))
        {
            if (buffer.Length == length)
            {
                return buffer;
            }
        }

        return new byte[length];
    }

    static void FlipRows(byte[] pixels, int rowBytes, int height)
    {
        var row = new byte[rowBytes];
        for (int top = 0, bottom = height - 1; top < bottom; top++, bottom--)
        {
            Buffer.BlockCopy(pixels, top * rowBytes, row, 0, rowBytes);
            Buffer.BlockCopy(pixels, bottom * rowBytes, pixels, top * rowBytes, rowBytes);
            Buffer.BlockCopy(row, 0, pixels, bottom * rowBytes, rowBytes);
        }
    }

    IEnumerator End(Session s)
    {
        float giveUpAt = Time.realtimeSinceStartup + DrainTimeoutS;
        while (Volatile.Read(ref s.InFlight) > 0 && Time.realtimeSinceStartup < giveUpAt)
        {
            yield return null;
        }

        Finish(s);
    }

    /// <summary>A quit mid-capture still leaves a frames.json: the readbacks are forced and the encodes given a moment.</summary>
    void OnApplicationQuit()
    {
        Session? s = session;
        session = null;
        if (s == null)
        {
            return;
        }

        AsyncGPUReadback.WaitAllRequests();
        for (int i = 0; i < 200 && Volatile.Read(ref s.InFlight) > 0; i++)
        {
            Thread.Sleep(10);
        }

        Finish(s);
    }

    void Finish(Session s)
    {
        float seconds = Time.realtimeSinceStartup - s.StartReal;
        FrameIndex.Entry[] frames = s.Frames.ToArray();
        int lost = Volatile.Read(ref s.InFlight);
        try
        {
            File.WriteAllText(Path.Combine(s.Dir, FrameIndex.IndexFile),
                FrameIndex.Json(Mathf.Max(1, fps.Value), s.Width, s.Height, s.Dropped, s.Failed + lost, frames));
        }
        catch (Exception e)
        {
            log.Error($"capture could not write {FrameIndex.IndexFile} in {s.Dir}: {e.Message}");
        }

        log.Info(Invariant($"capture stopped: {frames.Length} frames, {seconds:0.0} s, {s.Dropped} dropped, {s.Failed + lost} failed, {s.Dir}"));
    }
}

/// <summary>
/// The capture folder's contract with tools/Make-Video.ps1, Unity-free so tools/Test-FrameCapture.ps1 can load it from
/// the built DLL: frame file names, frames.json, and the capture pacing.
/// </summary>
public static class FrameIndex
{
    public const string IndexFile = "frames.json";

    /// <summary>
    /// One written frame. <see cref="SimS"/> is Time.time and <see cref="RealS"/> is Time.realtimeSinceStartup at capture,
    /// the trace's own t and wall, so a frame lines up with the trace.
    /// </summary>
    public readonly struct Entry
    {
        public Entry(int index, double simS, double realS, int frame)
        {
            Index = index;
            SimS = simS;
            RealS = realS;
            Frame = frame;
        }

        public int Index { get; }
        public double SimS { get; }
        public double RealS { get; }
        public int Frame { get; }
    }

    public static string FileName(int index) => "frame_" + index.ToString("D6", CultureInfo.InvariantCulture) + ".jpg";

    /// <summary>
    /// frames.json: the target rate, the first frame's size, frames dropped before capture (too many on their way) and
    /// failed after it, and every written frame in index order. Indices have gaps where a frame failed.
    /// </summary>
    public static string Json(int fps, int width, int height, int dropped, int failed, IEnumerable<Entry> frames)
    {
        var json = new StringBuilder();
        json.Append(Invariant($"{{\"fps\": {fps}, \"width\": {width}, \"height\": {height}, \"dropped\": {dropped}, \"failed\": {failed}, \"frames\": ["));
        bool first = true;
        foreach (Entry frame in frames.OrderBy(f => f.Index))
        {
            json.Append(first ? "\n  " : ",\n  ");
            json.Append(Invariant($"{{\"i\": {frame.Index}, \"file\": \"{FileName(frame.Index)}\", \"sim_s\": {frame.SimS:0.000}, \"real_s\": {frame.RealS:0.000}, \"frame\": {frame.Frame}}}"));
            first = false;
        }

        json.Append(first ? "]}\n" : "\n]}\n");
        return json.ToString();
    }

    /// <summary>
    /// Whether a frame ending at <paramref name="now"/> is captured. The beat holds at <paramref name="interval"/> on a game
    /// running faster than the target; after a slow frame it restarts from now rather than catching up in a burst.
    /// </summary>
    public static bool Due(float now, ref float nextAt, float interval)
    {
        if (now < nextAt)
        {
            return false;
        }

        nextAt += interval;
        if (nextAt <= now)
        {
            nextAt = now + interval;
        }

        return true;
    }
}
